# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=E1101

"""Umpired RPC command class."""

import os

import factory_common  # pylint: disable=W0611
from cros.factory.umpire.commands import deploy
from cros.factory.umpire.commands import import_bundle
from cros.factory.umpire.commands import status_reporter
from cros.factory.umpire.commands import update
from cros.factory.umpire import config
from cros.factory.umpire import daemon
from cros.factory.umpire import umpire_rpc
from cros.factory.utils import file_utils

class CLICommand(umpire_rpc.UmpireRPC):

  """Container of Umpire RPC commands.

  Umpire CLI commands are decorated with '@RPCCall'. Requests are translated
  via Twisted XMLRPC resource.

  Command returns:
    defer.Deferred: The server waits for the callback/errback and returns
                    the what callback/errback function returns.
    xmlrpc.Fault(): The raised exception will be catched by umpire.web.xmlrpc
                    and translate to xmlrpc.Fault with exception info.
    Other values: return to caller.
  """

  @umpire_rpc.RPCCall
  def Update(self, resources_to_update, source_id=None, dest_id=None):
    """Updates resource(s) in a bundle.

    It modifies active config and saves the result to staging.

    Args:
      resources_to_update: list of (resource_type, resource_path) to update.
      source_id: source bundle's ID. If omitted, uses default bundle.
      dest_id: If specified, it copies source bundle with ID dest_id and
          replaces the specified resource(s). Otherwise, it replaces
          resource(s) in place.

    Returns:
      Path to updated Umpire config file, which is marked as staging.
    """
    updater = update.ResourceUpdater(self.env)
    return updater.Update(resources_to_update, source_id, dest_id)

  @umpire_rpc.RPCCall
  def ImportBundle(self, bundle_path, bundle_id=None, note=None):
    """Imports a bundle.

    It reads a factory bundle and copies resources to Umpire.
    It also adds a bundle in UmpireConfig's bundles section and
    writes it to a staging config file.

    Args:
      bundle_path: A bundle's path (could be a directory or a zip file).
      bundle_id: The ID of the bundle. If omitted, use bundle_name in
          factory bundle's manifest.
      note: A note.

    Returns:
      Path to staging config.
    """
    importer = import_bundle.BundleImporter(self.env)
    return importer.Import(bundle_path, bundle_id, note)

  @umpire_rpc.RPCCall
  def AddResource(self, file_name, res_type=None):
    """Adds a file into base_dir/resources.

    Args:
      file_name: file to be added.
      res_type: (optional) resource type. If specified, it is one of the enum
        ResourceType. It tries to get version and fills in resource file name
        <base_name>#<version>#<hash>.

    Returns:
      Resource file name (base name).
    """
    return os.path.basename(self.env.AddResource(file_name, res_type=res_type))

  @umpire_rpc.RPCCall
  def InResource(self, file_name):
    """Queries if the file is in resources repository.

    Args:
      file_name: either full path or file name.

    Returns:
      True if the file is in resources respository.
    """
    return self.env.InResource(file_name)

  @umpire_rpc.RPCCall
  def GetStagingConfig(self):
    """Gets the staging config.

    Returns:
      Staging config file's content.
      '' if there's no staging config
    """
    return status_reporter.StatusReporter(self.env).GetStagingConfig()

  @umpire_rpc.RPCCall
  def UploadConfig(self, basename, content):
    """Uploads UmpireConfig string for Umpired to add to resources.

    It is used to solve the issue that Umpired cannot access edited config file
    generated by "umpire edit", which is in temporary directory only accessible
    by the user running CLI, not the user running Umpire server.

    Args:
      basename: UmpireConfig file's basename to be saved.
      content: UmpireConfig in string format.
    """
    with file_utils.TempDirectory() as temp_dir:
      config_file = os.path.join(temp_dir, basename)
      with open(config_file, 'w') as f:
        f.write(content)
      res_path = self.env.AddResource(config_file)
      return os.path.basename(res_path)

  @umpire_rpc.RPCCall
  def StageConfigFile(self, config_path, force=False):
    """Stages a config file.

    If a config file is not in resources directory, it will first add it
    to resources.

    Args:
      config_path: path to a config file to mark as staging. None or '' means
          staging active config.
      force: True to replace current staging config if exists.
    """
    if not config_path:
      # Stage active config file.
      self.env.StageConfigFile(None, force=force)
      return

    res_name = (os.path.basename(config_path)
                if self.env.InResource(config_path) else
                self.AddResource(config_path))
    config_path = self.env.GetResourcePath(res_name)
    self.env.StageConfigFile(config_path, force=force)

  @umpire_rpc.RPCCall
  def UnstageConfigFile(self):
    """Unstages the current staging config file.

    Returns:
      Real path of the staging file being unstaged.
    """
    return self.env.UnstageConfigFile()

  @umpire_rpc.RPCCall
  def ValidateConfig(self, umpire_config):
    """Validates a config.

    Args:
      umpire_config: UmpireConfig content or file path.

    Raises:
      TypeError: when 'services' is not a dict.
      KeyError: when top level key 'services' not found.
      SchemaException: on schema validation failed.
      UmpireError if there's any resources for active bundles missing.
    """
    config_to_validate = config.UmpireConfig(umpire_config)
    config.ValidateResources(config_to_validate, self.env)

  @umpire_rpc.RPCCall
  def Deploy(self, config_res):
    """Deploys a config file.

    It first verifies the config again, then tries reloading Umpire with the
    new config. If okay, removes current staging file and active the config.

    Args:
      config_res: a config file (base name, in resource folder) to deploy.

    Returns:
      Twisted deferred object.

    Raises:
      Exceptions when config fails to validate. See ValidateConfig() for
      exception type.
    """
    deployer = deploy.ConfigDeployer(self.env)
    return deployer.Deploy(config_res)

  @umpire_rpc.RPCCall
  def StopUmpired(self):
    """Stops Umpire daemon."""
    daemon.UmpireDaemon().Stop()

  @umpire_rpc.RPCCall
  def GetStatus(self):
    """Gets Umpire dameon status."""
    reporter = status_reporter.StatusReporter(self.env)
    return reporter.Report()
