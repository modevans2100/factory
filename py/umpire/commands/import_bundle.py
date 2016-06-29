# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Imports a bundle.

It reads a factory bundle, copies resources to Umpire repository, and
updates UmpireConfig.

See BundleImporter comments for usage.
"""

from datetime import datetime
import errno
import glob
import logging
import os
import re
import shutil
import tempfile
import yaml

import factory_common  # pylint: disable=W0611
from cros.factory.umpire.common import ResourceType, UmpireError
from cros.factory.umpire import config as umpire_config
from cros.factory.umpire import utils as umpire_utils
from cros.factory.utils import file_utils


def GetImageVersionFromManifest(manifest, image_type):
  """Gets image version from manifest's add_files field.

  Args:
    manifest: factory bundle's manifest dict.
    image_type: image type to get image version.

  Returns:
    image version of the type.

  Raises:
    Exception if image version not found.
  """
  # The image version in source URL contains:
  #   .../MAJOR.MINOR.BUILD/...
  # Where MAJOR, MINOR and BUILD are decimal digits.
  BUNDLE_IMAGE_VERSION_RE = re.compile(r'''.*/(\d+\.\d+\.\d+)/.*''')

  for f in manifest['add_files']:
    if image_type != f['install_into']:
      continue
    m = BUNDLE_IMAGE_VERSION_RE.match(f['source'])
    if m:
      return m.group(1)
    else:
      raise Exception('Image version string not found')
  raise Exception('Image type not found: ' + image_type)


def FakeGlobConstruct(unused_loader, unused_node):
  """Fake YAML constructor."""
  return None


class FactoryBundle(object):
  """Used to load a factory bundle.

  Uses Load() to load a bundle and parse manifest. Then the following
  properties provides path to components.

  Properties:
    manifest: factory bundle's MANIFEST dict.
    download_files_pattern: pattern of files for download.
    factory_toolkit: path to factory toolkit.
    netboot_image: path to netboot image.
    netboot_firmware: path to netboot BIOS image.
  """
  _BUNDLE_MANIFEST = 'MANIFEST.yaml'
  _DOWNLOAD_FILES_PATTERN = os.path.join('factory_setup', 'static', '*')
  _FACTORY_TOOLKIT = os.path.join('factory_toolkit',
                                  'install_factory_toolkit.run')
  _NETBOOT_IMAGE = os.path.join('factory_shim', 'netboot', 'vmlinux.uimg')
  _NETBOOT_FIRMWARE = os.path.join('netboot_firmware', 'image.net.bin')
  _MANDATORY_IMAGES = ['release', 'factory_shim']

  def __init__(self):
    self._path = None
    # Store factory bundle MANIFEST config.
    self._manifest = None

  @property
  def manifest(self):
    return self._manifest

  @property
  def download_files_pattern(self):
    return os.path.join(self._path, self._DOWNLOAD_FILES_PATTERN)

  @property
  def factory_toolkit(self):
    return os.path.join(self._path, self._FACTORY_TOOLKIT)

  @property
  def netboot_image(self):
    return os.path.join(self._path, self._NETBOOT_IMAGE)

  @property
  def netboot_firmware(self):
    return os.path.join(self._path, self._NETBOOT_FIRMWARE)

  def Load(self, path, temp_dir=None):
    """Loads a factory bundle.
    Also verifies the bundle's MANIFEST.yaml.

    Args:
      path: bundle path. Can be extracted path or zipped file.
      temp_dir: path to extract to if the bundle is zipped. If omitted and
          bundle is zipped, raise UmpireError.

    Raises:
      UmpireError if the bundle manifest is invalid.
    """
    if not os.path.exists(path):
      raise IOError(errno.ENOENT, 'Bundle does not exist', path)
    if not os.access(path, os.R_OK):
      raise IOError(
          errno.EACCES,
          'Bundle %r read permission denied. Make sure it is umpire readable',
          path)

    if os.path.isdir(path):
      self._path = path
    else:
      if not temp_dir:
        raise UmpireError('Bundle path %r is a file but no temp_dir for '
                          'extracting bundle.' % path)
      new_bundle_path = os.path.join(temp_dir, 'bundle')
      os.makedirs(new_bundle_path)
      file_utils.ExtractFile(path, new_bundle_path)
      self._path = new_bundle_path

    # Find the top-most directory in self._path which _BUNDLE_MANIFEST resides
    # as the modified self._path
    for subdir, _, files in os.walk(self._path):
      if self._BUNDLE_MANIFEST in files:
        if self._path != subdir:
          logging.info('Correct bundle base directory to %r', subdir)
          self._path = subdir
        break

    manifest_path = os.path.join(self._path, self._BUNDLE_MANIFEST)
    if not os.path.isfile(manifest_path):
      raise IOError(errno.ENOENT, 'MANIFEST.yaml does not exist', path)

    # Load MANIFEST.yaml and temporary uncheck mandatory images.
    # TODO(deanliao): figure out if the images are mandatory.
    try:
      yaml.add_constructor('!glob', FakeGlobConstruct)
      with open(manifest_path) as f:
        self._manifest = yaml.load(f)
        # for image_type in self._MANDATORY_IMAGES:
        #   GetImageVersionFromManifest(self._manifest, image_type)
    except Exception as e:
      raise UmpireError('Failed to load MANIFEST.yaml: ' + str(e))


class BundleImporter(object):
  """Imports a bundle.

  It reads a factory bundle and copies resources to Umpire.

  It also updates active UmpireConfig and saves it to staging. Note that if
  staging config alreay exists, it refuses to import the bundle.

  Usage:
    bundle_importer = BundleImporter(env)
    bundle_importer.Import('/path/to/bundle', 'bundle_id')
  """

  def __init__(self, env):
    """Constructor.

    Args:
      env: UmpireEnv object.
    """
    # Define _temp_dire before checking staging file. Otherwise, undefiend
    # _temp_dir will fail __del__, too.
    self._temp_dir = None

    if env.HasStagingConfigFile():
      raise UmpireError(
          'Cannot import bundle as staging config exists. '
          'Please run "umpire unstage" to unstage or "umpire deploy" to '
          'deploy the staging config first.')

    self._env = env
    self._factory_bundle = FactoryBundle()

    # Copy current config for editing.
    self._config = umpire_config.UmpireConfig(env.config)
    # Used for staging config's basename.
    self._config_basename = os.path.basename(os.path.realpath(env.config_path))

    # Store bundle config to be added to UmpireConfig.
    self._bundle = None
    self._shop_floor_handler = None

    # Download config's filename should be <board name>.conf.
    # Will set up in Import().
    self._download_config_path = None

    self._temp_dir = tempfile.mkdtemp()
    self._timestamp = datetime.utcnow()

  def __del__(self):
    if self._temp_dir and os.path.isdir(self._temp_dir):
      shutil.rmtree(self._temp_dir)

  def Import(self, bundle_path, bundle_id=None, note=None):
    """Imports a bundle.

    Args:
      bundle_path: A bundle's path (could be a directory or a zip file).
      bundle_id: The ID of the bundle. If omitted, use bundle_name in
          factory bundle's manifest.
      note: A description of this bundle. If omitted, use bundle_id.

    Returns:
      Updated staging config path.
    """
    self._factory_bundle.Load(bundle_path, self._temp_dir)

    # Sanity check: board must be the same.
    if self._factory_bundle.manifest['board'] != self._config['board']:
      raise UmpireError(
          "Board mismatch: Umpire's board: %r != bundle's board: %r" %
          (self._config['board'], self._factory_bundle.manifest['board']))

    self._download_config_path = os.path.join(
        self._temp_dir,
        '%s.conf' % self._config['board'])

    # Composes self._bundle.
    self._InitBundle(bundle_id, note)
    self._ImportResources()
    self._AddShopFloorConfig()

    # Adds a bundle in bundles section.
    self._config['bundles'].append(self._bundle)
    self._AddRuleset()

    return self._WriteToStagingConfig()

  def _InitBundle(self, bundle_id, note):
    if not bundle_id:
      bundle_id = self._factory_bundle.manifest['bundle_name']
    self._bundle = {'id': bundle_id,
                    'note': note if note else bundle_id}

    bundles = self._config.setdefault('bundles', [])
    if any(bundle_id == b['id'] for b in bundles):
      raise UmpireError('bundle_id: %r already in use' % bundle_id)

  def _ImportResources(self):
    """Adds resources from the bundle & updates bundle config.

    Raises:
      UmpireError if an hash collision is observed.
    """
    hash_collision_files = []
    resources = {}

    def AddResource(path, res_type=None):
      """Adds a file to Umpire resource repository.

      If hash collision is observed, append hash_collision_files.

      Args:
        path: file to add.
        res_type: (optional) resource type (enum of ResourceType.)

      Result:
        Basename of just added resource file. None if path does not exist or
        resource fails to add.
      """
      if not os.path.exists(path):
        return None
      try:
        resource_path = self._env.AddResource(path, res_type=res_type)
        return os.path.basename(resource_path)
      except UmpireError as e:
        if e.message.startswith('Hash collision'):
          hash_collision_files.append(path)
        return None

    def AddDownloadFiles():
      """Adds files in download_files_pattern in factory bundle to resources.

      It updates resources section in bundle by adding resources belongs to
      download config.

      Returns:
        List of added resources' filename.
      """
      # Mapping for download filename to (resource key, resource type).
      _RESOURCE_KEY_MAP = {
          'complete': ('complete_script', None),
          'efi': ('efi_partition', None),
          'firmware': ('firmware', ResourceType.FIRMWARE),
          'hwid': ('hwid', ResourceType.HWID),
          'oem': ('oem_partition', None),
          'rootfs-release': ('rootfs_release', ResourceType.ROOTFS_RELEASE),
          'rootfs-test': ('rootfs_test', ResourceType.ROOTFS_TEST),
          'state': ('stateful_partition', None)}

      download_files = []
      for path in glob.glob(self._factory_bundle.download_files_pattern):
        # Skip non-gzipped file.
        if not path.endswith('.gz'):
          continue
        # Remove '.gz' suffix.
        base_path = os.path.basename(path)[:-3]
        resource_key, resource_type = _RESOURCE_KEY_MAP.get(base_path,
                                                            (None, None))
        if not resource_key:
          continue
        resource_name = AddResource(path, res_type=resource_type)
        resources[resource_key] = resource_name
        download_files.append(resource_name)
      return download_files

    def WriteDownloadConfig(download_files):
      """Composes download config and adds it to resources.

      Based on given download_files, composes config file for netboot install.

      Args:
        download_files: list of resource names of download files.
      """
      # Content of download config.
      header = '# date:   %s\n# bundle: %s_%s\n' % (
          self._timestamp,
          self._factory_bundle.manifest['board'],
          self._factory_bundle.manifest['bundle_name'])

      body = umpire_utils.ComposeDownloadConfig(
          [self._env.GetResourcePath(r) for r in download_files])

      with open(self._download_config_path, 'w') as f:
        f.write(header)
        f.write(body)
      resources['download_conf'] = AddResource(self._download_config_path)

    # factory_toolkit is mandatory.
    if not os.path.isfile(self._factory_bundle.factory_toolkit):
      raise UmpireError('Missing factory toolkit %r' %
                        self._factory_bundle.factory_toolkit)
    resources['server_factory_toolkit'] = AddResource(
        self._factory_bundle.factory_toolkit,
        res_type=ResourceType.FACTORY_TOOLKIT)
    resources['device_factory_toolkit'] = resources['server_factory_toolkit']

    # Unpack device_factory_toolkit.
    umpire_utils.UnpackFactoryToolkit(self._env,
                                      resources['device_factory_toolkit'])

    resources['netboot_vmlinux'] = AddResource(
        self._factory_bundle.netboot_image,
        res_type=ResourceType.NETBOOT_VMLINUX)
    if not resources['netboot_vmlinux']:
      logging.warning('Missing netboot_vmlinux %r',
                      self._factory_bundle.netboot_image)

    resources['netboot_firmware'] = AddResource(
        self._factory_bundle.netboot_firmware,
        res_type=ResourceType.NETBOOT_FIRMWARE)
    if not resources['netboot_firmware']:
      logging.warning('Missing netboot_firmware %r',
                      self._factory_bundle.netboot_firmware)

    # Deal with files for netboot download.
    download_files = AddDownloadFiles()
    if not download_files:
      logging.warning('No files for download in %r',
                      self._factory_bundle.download_files_pattern)

    if hash_collision_files:
      raise UmpireError('Found %d hash collision: %r' % (
          len(hash_collision_files), hash_collision_files))

    WriteDownloadConfig(download_files)
    if not resources['download_conf']:
      logging.warning('Missing download_conf %r', self._download_config_path)

    self._bundle['resources'] = dict((k, v) for k, v in resources.items()
                                     if v is not None)

  def _AddShopFloorConfig(self):
    """Composes shop_floor section in bundle config."""
    shop_floor = {}
    if self._shop_floor_handler:
      shop_floor['handler'] = self._shop_floor_handler
    else:
      shop_floor['handler'] = ('cros.factory.umpire.%s_shop_floor_handler' %
                               self._factory_bundle.manifest['board'])
    # TODO(deanliao): add handler_config
    self._bundle['shop_floor'] = shop_floor

  def _AddRuleset(self):
    rulesets = self._config.setdefault('rulesets', [])
    ruleset = {
        'bundle_id': self._bundle['id'],
        'note': 'Please update match rule in ruleset',
        'active': False}
    rulesets.insert(0, ruleset)

  def _WriteToStagingConfig(self):
    """Writes self._config to resources and set it as staging.

    Returns:
      config path in resources.
    """
    temp_config_path = os.path.join(self._temp_dir, self._config_basename)
    self._config.WriteFile(temp_config_path)

    # Validate the about-to-stage config. Raise UmpireError if anything wrong.
    staging_config = umpire_config.UmpireConfig(temp_config_path)
    umpire_config.ValidateResources(staging_config, self._env)

    res_path = self._env.AddResource(temp_config_path)
    self._env.StageConfigFile(res_path)
    return res_path