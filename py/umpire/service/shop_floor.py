# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Shop floor service for launching shop floor XMLRPC in bundles."""


import logging
import os

import factory_common  # pylint: disable=W0611
from cros.factory.umpire.service import umpire_service


# TODO(rongchang): Check why symlink doesn't work.
SHOP_FLOOR_FCGI = 'usr/local/factory/py/umpire/shop_floor_launcher.py'
LOG_FILE_NAME = 'shop_floor.log'


class ExistingLogWriter(object):
  """ExistingLogWriter writes data to existing file only."""

  def __init__(self, path):
    super(ExistingLogWriter, self).__init__()
    self._path = path

  def write(self, data):
    if os.path.isfile(self._path):
      with open(self._path, 'a') as log:
        log.write(data)


class ShopFloorService(umpire_service.UmpireService):

  """Shop floor service.

  Example:
    shopfloor_service = GetServiceInstance('shop_floor')
    procs = svc.CreateProcesses(umpire_config_attrdict, umpire_env)
    shopfloor_service.Start(procs)
  """

  def __init__(self):
    super(ShopFloorService, self).__init__()
    self.properties['num_shopfloor_handlers'] = 0
    self.log = None

  def CreateProcesses(self, dummy_config, env):
    """Creates list of shop floor processes via config.

    Args:
      dummy_config: Umpire config AttrDict object.
      env: UmpireEnv object.

    Returns:
      A list of ServiceProcess.
    """
    self.log = ExistingLogWriter(os.path.join(env.log_dir, LOG_FILE_NAME))
    active_bundles = env.config.GetActiveBundles()
    processes = set()
    for bundle in active_bundles:
      # Get toolkit path and shop floor handler.
      toolkit_dir = env.GetBundleDeviceToolkit(bundle['id'])
      handler = bundle['shop_floor']['handler']
      if not (toolkit_dir and handler):
        continue
      # Prepare handler configuration.
      handler_config = bundle['shop_floor'].get('handler_config', dict())
      # Convert {'mount_point': '/path/to/dir'} to process parameters:
      #   ['--mount_point', '/path/to/dir']
      process_parameters = sum([['--%s' % key, value] for key, value in
                                handler_config.iteritems()], list())
      # Set process configuration.
      proc_config = {
          'executable': os.path.join(toolkit_dir, SHOP_FLOOR_FCGI),
          'name': bundle['id'],
          'args': ['--module', handler] + process_parameters,
          'path': env.umpire_data_dir}
      proc = umpire_service.ServiceProcess(self)
      proc.SetConfig(proc_config)
      # Skip duplicated bundle and prevent duplicate resource allocation.
      # Duplicate processes will be ignored in parent.Start().
      if proc in processes:
        continue

      if proc not in self.processes:
        # Allocate port and token.
        (fcgi_port, token) = env.shop_floor_manager.Allocate(bundle['id'])
        logging.debug('Allocate %s(%d,%s)', bundle['id'], fcgi_port, token)
        proc.SetNonhashArgs(['--port', str(fcgi_port), '--token', token])
        # Adds release callbacks on error and stopped state.

        def ReleaseResource():
          # pylint: disable=W0640
          logging.debug('Release %s(%d,%s)', bundle['id'], fcgi_port, token)
          env.shop_floor_manager.Release(fcgi_port)

        proc.AddStateCallback(umpire_service.State.DESTRUCTING, ReleaseResource)
      processes.add(proc)

    self.properties['num_shopfloor_handlers'] = len(processes)
    return list(processes)