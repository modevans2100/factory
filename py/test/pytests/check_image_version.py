# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# DESCRIPTION :
# This factory test checks image version in lsb-release. If the version doesn't
# match what's provided in the test argument, flash netboot firmware if it is
# provided.

from distutils import version
import logging
import time
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test.event_log import Log
from cros.factory.test import factory
from cros.factory.test import factory_task
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.utils import deploy_utils
from cros.factory.tools import flash_netboot
from cros.factory.umpire.client import get_update
from cros.factory.umpire.client import umpire_server_proxy
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import debug_utils


_TEST_TITLE = i18n_test_ui.MakeI18nLabel('Check Image Version')

_CSS = """
.start-font-size {
  font-size: 2em;
}
"""

# Messages for tasks
_MSG_VERSION_MISMATCH = i18n_test_ui.MakeI18nLabelWithClass(
    'Factory image version is incorrect. Please re-image this device.',
    'start-font-size test-error')
_MSG_NETWORK = i18n_test_ui.MakeI18nLabel('Please connect to ethernet.')
_MSG_NETBOOT = i18n_test_ui.MakeI18nLabel(
    'Factory image version is incorrect. Press space to re-image.')
_MSG_REIMAGING = i18n_test_ui.MakeI18nLabel('Flashing netboot firmware...')
_MSG_FLASH_ERROR = i18n_test_ui.MakeI18nLabelWithClass(
    'Error flashing netboot firmware!', 'start-font-size test-error')

_LSB_RELEASE_PATH = '/etc/lsb-release'

_SHOPFLOOR_TIMEOUT_SECS = 10
_RETRY_INTERVAL_SECS = 3


class ImageCheckTask(factory_task.FactoryTask):

  def __init__(self, test):
    super(ImageCheckTask, self).__init__()
    self._test = test
    self.dut = test.dut

  def CheckNetwork(self):
    while not self.dut.status.eth_on:
      time.sleep(0.5)
      self._test.template.SetState(_MSG_NETWORK)

  def PromptReimage(self):
    self._test.template.SetState(_MSG_NETBOOT)
    self._test.ui.BindKey(test_ui.SPACE_KEY, self.Reimage)

  def Reimage(self):
    if self._test.args.umpire:
      shopfloor_proxy = shopfloor.get_instance(
          detect=True, timeout=_SHOPFLOOR_TIMEOUT_SECS)
      netboot_firmware = get_update.GetUpdateForNetbootFirmware(shopfloor_proxy)
      if netboot_firmware:
        with open(flash_netboot.DEFAULT_NETBOOT_FIRMWARE_PATH, 'wb') as f:
          f.write(netboot_firmware)

    firmware_path = (self._test.args.netboot_fw or
                     flash_netboot.DEFAULT_NETBOOT_FIRMWARE_PATH)
    self._test.template.SetState(_MSG_REIMAGING)
    try:
      with self.dut.temp.TempFile() as temp_file:
        self.dut.link.Push(firmware_path, temp_file)
        factory_par = deploy_utils.CreateFactoryTools(self.dut)
        factory_par.CheckCall(
            ['flash_netboot', '-y', '-i', temp_file, '--no-reboot'],
            log=True)

      self.dut.CheckCall(['reboot'], log=True)

      self.Fail('Incorrect image version, DUT is rebooting to reimage.')
    except:  # pylint: disable=bare-except
      self._test.template.SetState(_MSG_FLASH_ERROR)

  def CheckImageFromUmpire(self):
    factory.console.info('Connecting to Umpire server...')
    shopfloor_client = None
    while True:
      try:
        shopfloor_client = shopfloor.get_instance(
            detect=True, timeout=_SHOPFLOOR_TIMEOUT_SECS)
        need_update = get_update.NeedImageUpdate(shopfloor_client)
        if need_update:
          logging.info('Umpire decide to update this DUT')
        else:
          logging.info('Umpire decide not to update this DUT')
        return need_update
      except umpire_server_proxy.UmpireServerProxyException:
        exception_string = debug_utils.FormatExceptionOnly()
        logging.info('Unable to sync with shopfloor server: %s',
                     exception_string)
      time.sleep(_RETRY_INTERVAL_SECS)

  def CheckImageVersion(self):
    if self._test.args.check_release_image:
      ver = self.dut.info.release_image_version
    else:
      ver = self.dut.info.factory_image_version
    Log('image_version', version=ver)
    version_format = (version.LooseVersion if self._test.args.loose_version
                      else version.StrictVersion)
    logging.info('Using version format: %r', version_format.__name__)
    logging.info('current version: %r', ver)
    logging.info('expected version: %r', self._test.args.min_version)
    return version_format(ver) < version_format(self._test.args.min_version)

  def Run(self):
    need_update = (self.CheckImageFromUmpire if self._test.args.umpire else
                   self.CheckImageVersion)
    if need_update():
      if self._test.args.reimage:
        self.CheckNetwork()
        if self._test.args.require_space:
          self.PromptReimage()
        else:
          self.Reimage()
      else:
        self._test.template.SetState(_MSG_VERSION_MISMATCH)
      return
    self.Pass()


class CheckImageVersionTest(unittest.TestCase):
  ARGS = [
      Arg('min_version', str,
          'Minimum allowed factory or release image version. If umpire is set, '
          ' this args will be neglected.', default=None, optional=True),
      Arg('loose_version', bool, 'Allow any version number representation.',
          default=False),
      Arg('netboot_fw', str, 'The path to netboot firmware image.',
          default=None, optional=True),
      Arg('reimage', bool, 'True to re-image when image version mismatch.',
          default=True, optional=True),
      Arg('require_space', bool,
          'True to require a space key press before reimaging.',
          default=True, optional=True),
      Arg('check_release_image', bool,
          'True to check release image instead of factory image.',
          default=False, optional=True),
      Arg('umpire', bool, 'True to check image update from Umpire server',
          default=False)]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self._task_list = [ImageCheckTask(self)]
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.ui.AppendCSS(_CSS)
    self.template.SetTitle(_TEST_TITLE)

  def runTest(self):
    factory_task.FactoryTaskManager(self.ui, self._task_list).Run()
