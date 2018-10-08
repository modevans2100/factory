# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Umpire bundle wrapper

We don't take advantage of django's database functionality because this system
should ideally be stateless. In other words, all information should be kept in
umpire instead of the database. This may not be possible for now, since umpire
config still lacks some critical information such as the history record.

TODO(littlecvr): make umpire config complete such that it contains all the
                 information we need.
"""

import contextlib
import copy
import errno
import logging
import os
import socket
import subprocess
import tempfile
import time
import traceback
import xmlrpclib

import django
import rest_framework.exceptions
import rest_framework.status

import factory_common  # pylint: disable=unused-import
from cros.factory.umpire import common as umpire_common
from cros.factory.umpire.server import resource as umpire_resource
from cros.factory.umpire.server.service import umpire_service
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import net_utils


# TODO(littlecvr): pull out the common parts between umpire and dome, and put
#                  them into a config file (using the new config API).
UMPIRE_BASE_PORT = 8080
UMPIRE_RPC_PORT_OFFSET = 2
UMPIRE_RSYNC_PORT_OFFSET = 4
UMPIRE_INSTALOG_PULL_SOCKET_PORT_OFFSET = 6
UMPIRE_START_WAIT_SECS = 5

# TODO(littlecvr): use volume container instead of absolute path.
# TODO(littlecvr): these constants are shared between here and cros_docker.sh,
#                  should be pulled out to common config.
FACTORY_SERVER_IMAGE_NAME = 'cros/factory_server'
DOCKER_SHARED_DIR = os.getenv('HOST_SHARED_DIR', '/cros_docker')
UMPIRE_DOCKER_DIR = os.getenv(
    'HOST_UMPIRE_DIR', os.path.join(DOCKER_SHARED_DIR, 'umpire'))
UMPIRE_DEFAULT_PROJECT_FILE = '.default_project'
UMPIRE_BASE_DIR_IN_UMPIRE_CONTAINER = '/var/db/factory/umpire'

DOCKER_SHARED_TMP_VOLUME = 'cros-docker-shared-tmp-vol'
SHARED_TMP_DIR = '/tmp/shared'
SHARED_TMP_STORAGE = django.core.files.storage.FileSystemStorage(
    location=SHARED_TMP_DIR)

TFTP_DOCKER_DIR = os.getenv(
    'HOST_TFTP_DIR', os.path.join(DOCKER_SHARED_DIR, 'tftp'))
TFTP_BASE_DIR_IN_TFTP_CONTAINER = '/var/tftp'
TFTP_ROOT_IN_DOME = '/var/tftp'
TFTP_ROOT_IN_UMPIRE_CONTAINER = '/mnt/tftp'
TFTP_CONTAINER_NAME = 'dome_tftp'

# Not every systems may provide a working /etc/localtime.
LOCALTIME_DOCKER_PATH = os.getenv('HOST_LOCALTIME_PATH', '/etc/localtime')

# Mount point of the Umpire data folder in Dome's container. Note: this is not
# Umpire base directory in Umpire's container (which is also
# '/var/db/factory/umpire', but they have nothing to do with each other). This
# is also not Umpire's base directory on host (which is '/cros_docker/umpire'
# for now).
# TODO(littlecvr): shared between here and cros_docker.sh, should be pulled out
#                  to a common config.
UMPIRE_BASE_DIR = '/var/db/factory/umpire'

UMPIRED_FILEPATH = '/usr/local/factory/bin/umpired'


logger = logging.getLogger('django.%s' % __name__)


class DomeException(rest_framework.exceptions.APIException):
  """Virtual base class of all Dome exceptions."""

  def __init__(self, detail=None, status_code=None):
    self.status_code = status_code or self.status_code
    super(DomeException, self).__init__(detail)


class DomeClientException(DomeException):
  """Errors that can be fixed by the client."""

  status_code = rest_framework.status.HTTP_400_BAD_REQUEST


class DomeServerException(DomeException):
  """Errors that cannot be fixed by the client."""

  status_code = rest_framework.status.HTTP_500_INTERNAL_SERVER_ERROR


def UploadedFilePath(uploaded_file):
  """Return path to the uploaded file."""
  return os.path.join(SHARED_TMP_DIR, uploaded_file.name)


@contextlib.contextmanager
def UploadedFile(temporary_uploaded_file_id):
  """Get corresponding file object path based on its ID."""
  f = TemporaryUploadedFile.objects.get(pk=temporary_uploaded_file_id)
  try:
    yield UploadedFilePath(f.file)
  finally:
    f.delete()  # delete the entry in database
    path = UploadedFilePath(f.file)
    try:
      os.unlink(path)  # once the file has been used it can be removed
    except OSError as e:
      if e.errno != errno.ENOENT:  # don't care if it's been removed already
        raise
    try:
      os.rmdir(os.path.dirname(path))  # also try to remove empty directory
    except OSError as e:
      if e.errno != errno.ENOTEMPTY:  # but don't care if it's not empty
        raise


def GetUmpireServerFromPort(port):
  host = net_utils.GetDockerHostIP()
  url = 'http://%s:%d' % (host, port + UMPIRE_RPC_PORT_OFFSET)
  return xmlrpclib.ServerProxy(url, allow_none=True)


def GetUmpireServer(project_name):
  project = Project.objects.get(pk=project_name)
  return GetUmpireServerFromPort(project.umpire_port)


def GetUmpireConfig(project_name):
  return json_utils.LoadStr(GetUmpireServer(project_name).GetActiveConfig(),
                            convert_to_str=False)


def GenerateUploadToPath(unused_instance, filename):
  """Generate a unique file path string in django's media root.

  This callable is used by the file field of TemporaryUploadedFile. The main
  purpose of using a callable instead of a simple string is to preserve the
  original file name uploaded by the user. If using a simple string, and
  multiple files with the same name were uploaded at the same time, django would
  add a random suffix to the later one, making it losing its original file name.
  """
  # create media root if needed, or mkdtemp would fail
  try:
    os.makedirs(SHARED_TMP_DIR)
  except OSError as e:
    if e.errno != errno.EEXIST:
      raise

  # add a time string as prefix for better debugging experience
  temp_dir = tempfile.mkdtemp(prefix='%s-' % time.strftime('%Y%m%d%H%M%S'),
                              dir=SHARED_TMP_DIR)
  path = os.path.relpath(os.path.join(temp_dir, filename), SHARED_TMP_DIR)
  logger.info('Uploading file to %r', path)
  return path


def DoesContainerExist(container_name):
  container_list = subprocess.check_output([
      'docker', 'ps', '--all', '--format', '{{.Names}}']).splitlines()
  return container_name in container_list


class DomeConfig(django.db.models.Model):

  id = django.db.models.IntegerField(
      default=0, primary_key=True, serialize=False)
  tftp_enabled = django.db.models.BooleanField(default=False)

  def CreateTFTPContainer(self):
    if DoesContainerExist(TFTP_CONTAINER_NAME):
      logger.info('TFTP container already exists')
      return self

    try:
      cmd = [
          'docker', 'run', '--detach',
          '--restart', 'unless-stopped',
          '--name', TFTP_CONTAINER_NAME,
          '--volume', '%s:%s' % (TFTP_DOCKER_DIR,
                                 TFTP_BASE_DIR_IN_TFTP_CONTAINER),
          '--net', 'host',
          FACTORY_SERVER_IMAGE_NAME,
          'dnsmasq', '--user=root', '--port=0',
          '--enable-tftp', '--tftp-root=%s' % TFTP_BASE_DIR_IN_TFTP_CONTAINER,
          '--no-daemon', '--no-resolv'
      ]
      logger.info('Running command %r', cmd)
      subprocess.check_call(cmd)
    except Exception:
      logger.error('Failed to create TFTP container')
      logger.exception(traceback.format_exc())
      self.DeleteTFTPContainer()
      raise

    self.tftp_enabled = True
    self.save()

    return self

  def DeleteTFTPContainer(self):
    logger.info('Deleting TFTP container')
    subprocess.call(['docker', 'rm', '-f', TFTP_CONTAINER_NAME])
    self.tftp_enabled = False
    self.save()
    return self

  def UpdateConfig(self, **kwargs):
    # enable or disable TFTP if necessary
    self.tftp_enabled = DoesContainerExist(TFTP_CONTAINER_NAME)
    if ('tftp_enabled' in kwargs and
        self.tftp_enabled != kwargs['tftp_enabled']):
      if kwargs['tftp_enabled']:
        self.CreateTFTPContainer()
      else:
        self.DeleteTFTPContainer()

    # update attributes assigned in kwargs
    for attr, value in kwargs.iteritems():
      if hasattr(self, attr):
        setattr(self, attr, value)
    self.save()

    return self


class TemporaryUploadedFieldFile(django.db.models.fields.files.FieldFile):
  """A FieldFile that propogates the temporary_file_path of underlying file."""
  def temporary_file_path(self):
    return self.file.temporary_file_path()


class TemporaryUploadedFileField(django.db.models.FileField):
  """A FileField that works better with TemporaryFileUploadHandler.

  When creating a model instance, django would always try to convert the value
  of a FileField into a FieldFile (See
  django.db.models.fields.files.FileDescriptor.__get__). But the storage would
  only move the file to target location if the value have attribute
  temporary_file_path (See django.core.file.storage.FileSystemStorage._save).
  Since django doesn't pass the temporary_file_path when wrapping the field
  value (originally an django.core.files.uploadedfile.TemporaryUploadedFile)
  into a FieldFile, django would do an extra copy when actually saving the
  model.

  To fix this, we inherit FieldFile to a new class TemporaryUploadedFieldFile,
  set temporary_file_path correctly, and use that in this
  TemporaryUploadedFileField.
  """
  attr_class = TemporaryUploadedFieldFile


class TemporaryUploadedFile(django.db.models.Model):
  """Model to hold temporary uploaded files from user.

  The API of Dome is designed as: if a request contains N files, split it into
  (N+1) requests, with first N request uploading each file (encoded in
  multipart/form-data), and the last request sending other fields (encoded in
  JSON). Each file uploading request gets a file ID, in the last request, we
  refer to a file using its ID we got before.

  For example, if we want to send a request:
  {
    "foo": "bar",
    "hello": "world",
    "file01": a file object,
    "file02": another file object
  }
  We split it into 3 requests:
  1. Send {"file": a file object} in multipart/form-data, suppose we got ID
     1005.
  2. Send {"file": another file object} in multipart/form-data, suppose we got
     ID 1008.
  3. Send
     {
       "foo": "bar",
       "hello": "world",
       "file01": 1005,
       "file02": 1008
     }
     in JSON.
  """

  file = TemporaryUploadedFileField(
      storage=SHARED_TMP_STORAGE, upload_to=GenerateUploadToPath)
  created = django.db.models.DateTimeField(auto_now_add=True)


class Project(django.db.models.Model):

  # TODO(littlecvr): max_length should be shared with Umpire and serializer
  name = django.db.models.CharField(max_length=200, primary_key=True)
  umpire_enabled = django.db.models.BooleanField(default=False)
  umpire_port = django.db.models.PositiveIntegerField(null=True)
  netboot_bundle = django.db.models.CharField(max_length=200, null=True)

  # TODO(littlecvr): add TFTP and Overlord ports

  class Meta(object):
    ordering = ['name']

  @property
  def has_existing_umpire(self):
    return self.GetExistingUmpirePort() is not None

  def GetExistingUmpirePort(self):
    if self.umpire_enabled:
      return self.umpire_port

    container_name = Project.GetUmpireContainerName(self.name)
    if not DoesContainerExist(container_name):
      return None
    return int(subprocess.check_output([
        'docker', 'inspect', '--format',
        '{{(index (index .NetworkSettings.Ports "%s/tcp") 0).HostPort}}' %
        UMPIRE_BASE_PORT, container_name
    ]))

  @staticmethod
  def GetProjectByName(project_name):
    return Project.objects.get(pk=project_name)

  def UploadAndDeployConfig(self, config):
    """Upload and deploy config atomically."""
    umpire_server = GetUmpireServer(self.name)

    logger.info('Uploading Umpire config')

    new_config_path = umpire_server.AddConfigFromBlob(
        json_utils.DumpStr(config, pretty=True),
        umpire_resource.ConfigTypeNames.umpire_config)

    logger.info('Deploying Umpire config')
    try:
      umpire_server.Deploy(new_config_path)
    except xmlrpclib.Fault as e:
      logger.error(
          'Deploying failed. Error message from Umpire: %r', e.faultString)
      # TODO(littlecvr): we should probably refine Umpire's error message so
      #                  Dome has to forward the message to the user only
      #                  without knowing what's really happened
      if 'Missing default bundle' in e.faultString:
        raise DomeClientException(
            detail='Cannot remove or deactivate default bundle')
      else:
        raise DomeServerException(detail=e.faultString)

  def GetNormalizedActiveConfig(self):
    """Return the normalized version of Umpire active config."""
    return self.NormalizeConfig(GetUmpireConfig(self.name))

  @staticmethod
  def NormalizeConfig(config):
    bundle_id_set = set(b['id'] for b in config['bundles'])

    # We do not allow multiple rulesets referring to the same bundle, so
    # duplicate the bundle if we have found such cases.
    ruleset_id_set = set()
    for r in config['rulesets']:
      # TODO(littlecvr): how to deal with a ruleset that refers to a
      #                  non-existing bundle?

      if r['bundle_id'] not in ruleset_id_set:
        ruleset_id_set.add(r['bundle_id'])
      else:  # need to duplicate
        # generate a new name, may generate very long _copy_copy_copy... at the
        # end if there are many conflicts
        new_name = r['bundle_id']
        while True:
          new_name = '%s_copy' % new_name
          if new_name not in ruleset_id_set and new_name not in bundle_id_set:
            ruleset_id_set.add(new_name)
            bundle_id_set.add(new_name)
            break

        # find the original bundle and duplicate it
        src_bundle = next(
            b for b in config['bundles'] if b['id'] == r['bundle_id'])
        dst_bundle = copy.deepcopy(src_bundle)
        dst_bundle['id'] = new_name
        config['bundles'].append(dst_bundle)

        # update the ruleset
        r['bundle_id'] = new_name

      # The key match is deprecated.
      r.pop('match', None)

    # sort 'bundles' section by their IDs
    config['bundles'].sort(key=lambda b: b['id'])

    # We do not allow bundles exist in 'bundles' section but not in 'ruleset'
    # section.
    for b in config['bundles']:
      if b['id'] not in ruleset_id_set:
        ruleset_id_set.add(b['id'])
        config['rulesets'].append({'active': False,
                                   'bundle_id': b['id'],
                                   'note': b['note']})

    return config

  def MapNetbootResourceToTFTP(self, bundle_name):
    umpire_server = GetUmpireServer(self.name)
    netboot_resources = [
        (umpire_resource.PayloadTypeNames.netboot_kernel, 'vmlinuz'),
        (umpire_resource.PayloadTypeNames.netboot_cmdline, 'cmdline')
    ]
    for (payload_type, file_name) in netboot_resources:
      tftp_path = os.path.join('chrome-bot', self.name, file_name)
      # remove old resources
      file_utils.TryUnlink(os.path.join(TFTP_ROOT_IN_DOME, tftp_path))
      if Bundle.HasResource(self.name, bundle_name, payload_type):
        path_in_umpire = os.path.join(TFTP_ROOT_IN_UMPIRE_CONTAINER, tftp_path)
        umpire_server.ExportPayload(bundle_name, payload_type, path_in_umpire)
    return self

  def GetUmpireVersion(self):
    logger.info('Waiting for umpire localhost:%s to start', self.umpire_port)
    start_time = time.time()
    while time.time() < start_time + UMPIRE_START_WAIT_SECS:
      try:
        server = GetUmpireServerFromPort(self.umpire_port)
        version = server.GetVersion()
        break
      except socket.error:
        # The server is not ready yet.
        pass
      except xmlrpclib.Fault as e:
        if e.faultCode == xmlrpclib.METHOD_NOT_FOUND:
          # Assume that this is an umpire server before the GetVersion is
          # introduced.
          version = 0
          break
        raise
      time.sleep(0.2)
    else:
      raise DomeClientException(
          "Can't connect to umpire after %d seconds." % UMPIRE_START_WAIT_SECS)
    logger.info('Connected to umpire server (version=%d)', version)
    return version

  def AddExistingUmpireContainer(self):
    """Add an existing Umpire container to the database."""
    container_name = Project.GetUmpireContainerName(self.name)
    logger.info('Adding Umpire container %r', container_name)
    port = self.GetExistingUmpirePort()
    self.umpire_enabled = True
    self.umpire_port = port
    self.save()
    self.TryRestartOldUmpireContainer()
    return self

  def CreateUmpireContainer(self, port):
    """Create a local Umpire container from a factory toolkit."""
    # make sure the container does not exist
    container_name = Project.GetUmpireContainerName(self.name)
    logger.info('Creating Umpire container %r', container_name)

    try:
      # create and start a new container
      # TODO(littlecvr): this is almost identical to cros_docker.sh's
      #                  do_umpire_run() function, we should remove this
      #                  function in that script because this job should be
      #                  done by Dome only
      cmd = [
          'docker', 'run', '--detach', '--privileged',
          '--tmpfs', '/run:rw,size=16384k',
          '--volume', '%s:/mnt' % DOCKER_SHARED_DIR,
          '--volume', '%s/%s:%s' % (UMPIRE_DOCKER_DIR,
                                    self.name,
                                    UMPIRE_BASE_DIR_IN_UMPIRE_CONTAINER),
          '--volume', '%s:%s' % (DOCKER_SHARED_TMP_VOLUME, SHARED_TMP_DIR),
          '--publish', '%d:%d' % (port, UMPIRE_BASE_PORT),
          '--publish', '%d:%d' % (port + UMPIRE_RPC_PORT_OFFSET,
                                  UMPIRE_BASE_PORT + UMPIRE_RPC_PORT_OFFSET),
          '--publish', '%d:%d' % (port + UMPIRE_RSYNC_PORT_OFFSET,
                                  UMPIRE_BASE_PORT + UMPIRE_RSYNC_PORT_OFFSET),
          '--publish', '%d:%d' % (port +
                                  UMPIRE_INSTALOG_PULL_SOCKET_PORT_OFFSET,
                                  UMPIRE_BASE_PORT +
                                  UMPIRE_INSTALOG_PULL_SOCKET_PORT_OFFSET),
          '--env', 'UMPIRE_PROJECT_NAME=%s' % self.name,
          '--restart', 'unless-stopped',
          '--name', container_name]
      if LOCALTIME_DOCKER_PATH:
        cmd += ['--volume', '%s:/etc/localtime:ro' % LOCALTIME_DOCKER_PATH]
      cmd += [FACTORY_SERVER_IMAGE_NAME, UMPIRED_FILEPATH]
      logger.info('Running command %r', cmd)
      subprocess.check_call(cmd)
      # Update default project for 'cros_docker.sh umpire' commands.
      with open(os.path.join(UMPIRE_BASE_DIR,
                             UMPIRE_DEFAULT_PROJECT_FILE), 'w') as f:
        f.write(self.name)
    except Exception:
      logger.error('Failed to create Umpire container %r', container_name)
      logger.exception(traceback.format_exc())
      # remove container
      subprocess.call(['docker', 'stop', container_name])
      subprocess.call(['docker', 'rm', container_name])
      raise

    # push into the database
    self.umpire_enabled = True
    self.umpire_port = port
    self.save()
    return self

  def DeleteUmpireContainer(self):
    logger.info('Deleting Umpire container %r', self.name)
    container_name = Project.GetUmpireContainerName(self.name)
    subprocess.call(['docker', 'stop', container_name])
    subprocess.call(['docker', 'rm', container_name])
    self.umpire_enabled = False
    self.save()
    return self

  def TryRestartOldUmpireContainer(self):
    if not self.umpire_enabled:
      return

    version = self.GetUmpireVersion()
    if version == umpire_common.UMPIRE_VERSION:
      return

    logger.info('Restarting old Umpire container for %s at port %d '
                '(version = %d, latest version = %d)', self.name,
                self.umpire_port, version, umpire_common.UMPIRE_VERSION)
    self.DeleteUmpireContainer()
    self.CreateUmpireContainer(self.umpire_port)

    version = self.GetUmpireVersion()
    if version != umpire_common.UMPIRE_VERSION:
      raise DomeServerException(
          "Umpire version of new instance (%d) doesn't "
          'match the version of what Dome expected (%d).' %
          (version, umpire_common.UMPIRE_VERSION))

    logger.info('Umpire container for %s had been restarted.', self.name)

  @staticmethod
  def GetUmpireContainerName(name):
    return 'umpire_%s' % name

  @staticmethod
  def CreateOne(name, **kwargs):
    logger.info('Creating new project %r', name)
    project = Project.objects.create(name=name)
    try:
      return Project.UpdateOne(project, **kwargs)
    except Exception:
      logger.error('Failed to create project %r', name)
      logger.exception(traceback.format_exc())
      # delete the entry if anything goes wrong
      try:
        Project.objects.get(pk=name).delete()
      except django.core.exceptions.ObjectDoesNotExist:
        pass
      except Exception:
        raise

  @staticmethod
  def UpdateOne(project, **kwargs):
    logger.info('Updating project %r', project.name)
    # enable or disable Umpire if necessary
    if ('umpire_enabled' in kwargs and
        project.umpire_enabled != kwargs['umpire_enabled']):
      if not kwargs['umpire_enabled']:
        project.DeleteUmpireContainer()
      else:
        container_name = Project.GetUmpireContainerName(project.name)
        if DoesContainerExist(container_name):
          project.AddExistingUmpireContainer()
        else:
          project.CreateUmpireContainer(kwargs['umpire_port'])

    # replace netboot resource in TFTP root
    if ('netboot_bundle' in kwargs and
        project.netboot_bundle != kwargs['netboot_bundle']):
      project.MapNetbootResourceToTFTP(kwargs['netboot_bundle'])

    # update attributes assigned in kwargs
    for attr, value in kwargs.iteritems():
      if hasattr(project, attr):
        setattr(project, attr, value)
    project.save()

    return project


class Resource(object):

  def __init__(self, type_name, version):
    self.type = type_name
    self.version = version

  @staticmethod
  def CreateOne(project_name, type_name, file_id):
    umpire_server = GetUmpireServer(project_name)
    with UploadedFile(file_id) as p:
      payloads = umpire_server.AddPayload(p, type_name)
    return Resource(type_name, payloads[type_name]['version'])


class Bundle(object):
  """Represent a bundle in umpire."""

  def __init__(self, name, note, active, payloads):
    self.name = name
    self.note = note
    self.active = active

    self.resources = {type_name: Resource(type_name, 'N/A')
                      for type_name in umpire_resource.PayloadTypeNames}
    for type_name in payloads:
      self.resources[type_name] = Resource(type_name,
                                           payloads[type_name]['version'])

  @staticmethod
  def HasResource(project_name, bundle_name, resource_name):
    project = Project.GetProjectByName(project_name)
    config = project.GetNormalizedActiveConfig()
    bundle = next(b for b in config['bundles'] if b['id'] == bundle_name)
    payloads = GetUmpireServer(project_name).GetPayloadsDict(bundle['payloads'])
    return resource_name in payloads

  @staticmethod
  def _FromUmpireBundleAndRuleset(project_name, bundle, ruleset):
    """Take the target entry in the "bundles" and "rulesets" sections in Umpire
    config, and turns them into the Bundle entity in Dome.

    Args:
      bundle: the target bundle in the "bundles" section in Umpire config.
      ruleset: ruleset that refers the the target bundle in Umpire config.
    """
    payloads = GetUmpireServer(project_name).GetPayloadsDict(bundle['payloads'])
    return Bundle(bundle['id'],  # name
                  ruleset['note'],  # note
                  ruleset['active'],  # active
                  payloads)  # payloads

  @staticmethod
  def DeleteOne(project_name, bundle_name):
    """Delete a bundle in Umpire config.

    Args:
      project_name: name of the project.
      bundle_name: name of the bundle to delete.
    """
    project = Project.GetProjectByName(project_name)
    config = project.GetNormalizedActiveConfig()
    if not any(b['id'] == bundle_name for b in config['bundles']):
      raise DomeClientException(
          detail='Bundle %s not found' % bundle_name,
          status_code=rest_framework.status.HTTP_404_NOT_FOUND)

    config['rulesets'] = [
        r for r in config['rulesets'] if r['bundle_id'] != bundle_name]
    config['bundles'] = [
        b for b in config['bundles'] if b['id'] != bundle_name]

    project.UploadAndDeployConfig(config)

  @staticmethod
  def ListOne(project_name, bundle_name):
    """Return the bundle that matches the search criterion.

    Args:
      project_name: name of the project.
      bundle_name: name of the bundle to find, this corresponds to the "id"
          field in umpire config.
    """
    project = Project.GetProjectByName(project_name)
    config = project.GetNormalizedActiveConfig()

    logger.info('Finding bundle %r in project %r', bundle_name, project_name)
    try:
      ruleset = next(
          r for r in config['rulesets'] if r['bundle_id'] == bundle_name)
      bundle = next(b for b in config['bundles'] if b['id'] == bundle_name)
    except StopIteration:
      logger.exception(traceback.format_exc())
      error_message = 'Bundle %r does not exist' % bundle_name
      logger.error(error_message)
      raise DomeClientException(error_message)

    return Bundle._FromUmpireBundleAndRuleset(project_name, bundle, ruleset)

  @staticmethod
  def ListAll(project_name):
    """Return all bundles as a list.

    This function lists bundles in the following order:
    1. bundles in the 'rulesets' section
    2. bundles in the 'bunedles' section but not in the 'rulesets' section

    Args:
      project_name: name of the project.

    Return:
      A list of all bundles.
    """
    project = Project.GetProjectByName(project_name)
    config = project.GetNormalizedActiveConfig()

    bundle_dict = dict((b['id'], b) for b in config['bundles'])

    bundle_list = []
    for r in config['rulesets']:
      b = bundle_dict[r['bundle_id']]
      bundle_list.append(Bundle._FromUmpireBundleAndRuleset(project_name, b, r))

    return bundle_list

  @staticmethod
  def ModifyOne(project_name, src_bundle_name, dst_bundle_name=None,
                note=None, active=None, resources=None):
    """Modify a bundle.

    Args:
      project_name: name of the project.
      src_bundle_name: name of the bundle to update.
      dst_bundle_name: if None, do an in-place update; otherwise, duplicate the
          bundle, name it dst_bundle_name, then update it.
      note: note of the bundle.
      active: True to make the bundle active, False to make the bundle inactive.
          None means no change.
      resources: a dict deserialized by ResourceSerializer, listing all
          resources that should be updated. If a resource is not listed, nothing
          would be changed to the particular resource, so the client can do
          partial update without listing all resources.
    """
    project = Project.GetProjectByName(project_name)
    config = project.GetNormalizedActiveConfig()

    try:
      src_bundle = next(
          b for b in config['bundles'] if b['id'] == src_bundle_name)
      src_ruleset = next(
          r for r in config['rulesets'] if r['bundle_id'] == src_bundle_name)
    except StopIteration:
      logger.exception(traceback.format_exc())
      error_message = 'Bundle %r does not exist' % src_bundle_name
      logger.error(error_message)
      raise DomeClientException(error_message)

    if not dst_bundle_name:
      # in-place update
      bundle = src_bundle
      ruleset = src_ruleset
    else:
      if any(b for b in config['bundles'] if b['id'] == dst_bundle_name):
        raise DomeClientException(
            detail='Bundle "%s" already exists' % dst_bundle_name,
            status_code=rest_framework.status.HTTP_409_CONFLICT)
      # not in-place update, duplicate the source bundle
      bundle = copy.deepcopy(src_bundle)
      bundle['id'] = dst_bundle_name
      config['bundles'].insert(0, bundle)
      ruleset = copy.deepcopy(src_ruleset)
      ruleset['bundle_id'] = dst_bundle_name
      config['rulesets'].insert(0, ruleset)
      config = project.NormalizeConfig(config)

    if note is not None:
      # TODO(littlecvr): unit tests for unicode.
      bundle['note'] = note
      ruleset['note'] = note

    if active is not None:
      ruleset['active'] = active

    # only deploy if at least one thing has changed
    if dst_bundle_name or note is not None or active is not None:
      project.UploadAndDeployConfig(config)

    # update resources
    if resources is not None:
      for resource_key, resource in resources.iteritems():
        Bundle._UpdateResource(project_name, bundle['id'], resource_key,
                               resource['file_id'])

    return Bundle.ListOne(project_name, bundle['id'])

  @staticmethod
  def ReorderBundles(project_name, new_order):
    """Reorder the bundles in Umpire config.

    TODO(littlecvr): make sure this also works if multiple users are using at
                     the same time.

    Args:
      new_order: a list of bundle names.
    """
    project = Project.GetProjectByName(project_name)
    old_config = project.GetNormalizedActiveConfig()

    # make sure all names are in current config
    old_bundle_set = set(b['id'] for b in old_config['bundles'])
    new_bundle_set = set(new_order)
    if old_bundle_set != new_bundle_set:
      raise DomeClientException('All bundles must be listed when reordering')

    # build a map for fast query later
    rulesets = dict((r['bundle_id'], r) for r in old_config['rulesets'])

    # reorder bundles
    new_config = copy.deepcopy(old_config)
    new_config['rulesets'] = [rulesets[n] for n in new_order]

    project.UploadAndDeployConfig(new_config)

    return Bundle.ListAll(project_name)

  @staticmethod
  def _UpdateResource(project_name, bundle_name, type_name, resource_file_id):
    """Update resource in a bundle.

    Args:
      project_name: name of the project.
      bundle_name: the bundle to update.
      type_name: An element of umpire_resource.PayloadTypeNames.
      resource_file_id: id of the resource file (id of TemporaryUploadedFile).
    """
    umpire_server = GetUmpireServer(project_name)
    with UploadedFile(resource_file_id) as p:
      try:
        umpire_server.Update([(type_name, p)], bundle_name)
      except xmlrpclib.Fault as e:
        raise DomeServerException(detail=e.faultString)

  @staticmethod
  def UploadNew(project_name, bundle_name, bundle_note, bundle_file_id):
    """Upload a new bundle.

    Args:
      project_name: name of the project.
      bundle_name: name of the new bundle, in string. This corresponds to the
          "id" field in umpire config.
      bundle_note: commit message. This corresponds to the "note" field in
          umpire config.
      bundle_file_id: id of the bundle file (id of TemporaryUploadedFile).

    Return:
      The newly created bundle.
    """
    umpire_server = GetUmpireServer(project_name)

    with UploadedFile(bundle_file_id) as p:
      try:
        umpire_server.ImportBundle(p, bundle_name, bundle_note)
      except xmlrpclib.Fault as e:
        if 'already in use' in e.faultString:
          raise DomeClientException(
              detail='Bundle "%s" already exists' % bundle_name,
              status_code=rest_framework.status.HTTP_409_CONFLICT)
        else:
          raise DomeServerException(detail=e.faultString)

    config = GetUmpireConfig(project_name)
    for ruleset in config['rulesets']:
      if ruleset['bundle_id'] == bundle_name:
        ruleset['note'] = bundle_note
        ruleset['active'] = True
        break

    project = Project.GetProjectByName(project_name)
    project.UploadAndDeployConfig(config)

    # find and return the new bundle
    return Bundle.ListOne(project_name, bundle_name)


class Service(object):
  """Represent a service config in Umpire."""

  def __init__(self, name, config):
    self.name = name
    self.config = config

  @staticmethod
  def GetServiceSchemata():
    return umpire_service.GetAllServiceSchemata().schema['properties']

  @staticmethod
  def ListAll(project_name):
    project = Project.objects.get(pk=project_name)
    return project.GetNormalizedActiveConfig()['services']

  @staticmethod
  def Update(project_name, data):
    project = Project.GetProjectByName(project_name)
    config = project.GetNormalizedActiveConfig()
    config['services'].update(data)
    return project.UploadAndDeployConfig(config)


class ParameterDirectory(object):

  def __init__(self, id, parent_id, name, children_ids):
    # pylint: disable=redefined-builtin
    self.id = id
    self.parent_id = parent_id
    self.name = name
    self.children_ids = children_ids

  @staticmethod
  def CreateOne(project_name, parent_id, name):
    umpire_server = GetUmpireServer(project_name)
    directory = umpire_server.CreateParameterDirectory(parent_id, name)
    return ParameterDirectory(**directory)

  @staticmethod
  def ListAll(project_name):
    umpire_server = GetUmpireServer(project_name)
    parameters = umpire_server.GetParameterInfo()
    return [ParameterDirectory(**p) for p in parameters['dirs']]


class ParameterComponent(object):

  def __init__(self, id, dir_id, name, using_ver, revisions):
    # pylint: disable=redefined-builtin
    self.id = id
    self.dir_id = dir_id
    self.name = name
    self.using_ver = using_ver
    self.revisions = revisions

  @staticmethod
  def CreateOne(project_name, id, dir_id, name, using_ver, file_id):
    # pylint: disable=redefined-builtin
    umpire_server = GetUmpireServer(project_name)
    try:
      component = None
      if file_id:
        with UploadedFile(file_id) as file_path:
          component = umpire_server.UpdateParameterComponent(
              id, dir_id, name, using_ver, file_path)
      else:
        component = umpire_server.UpdateParameterComponent(
            id, dir_id, name, using_ver)
      return ParameterComponent(**component)
    except xmlrpclib.Fault as e:
      raise DomeServerException(detail=e.faultString)
    return None

  @staticmethod
  def ListAll(project_name):
    umpire_server = GetUmpireServer(project_name)
    parameters = umpire_server.GetParameterInfo()
    return [ParameterComponent(**p) for p in parameters['files']]
