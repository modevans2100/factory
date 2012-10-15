# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runs chromeos-firmwareupdate to force update EC/firmware."""

import logging
import os
import subprocess
import threading
import unittest

from cros.factory.test.args import Arg
from cros.factory.test.test_ui import Escape, MakeLabel, UI
from cros.factory.test.ui_templates import OneScrollableSection
from cros.factory.utils.process_utils import Spawn

_TEST_TITLE = MakeLabel('Update Firmware', u'更新韧体')
_CSS = '#state {text-align:left;}'


class UpdateFirmwareTest(unittest.TestCase):
  ARGS = [
    Arg('firmware_updater', str, 'Full path of chromeos-firmwareupdate.',
        default='/usr/local/factory/custom/chromeos-firmwareupdate'),
    Arg('update_ec', bool, 'Update embedded firmware.', default=True),
    Arg('update_main', bool, 'Update main firmware.', default=True),
  ]

  def setUp(self):
    self.assertTrue(os.path.isfile(self.args.firmware_updater),
                    msg='%s is missing.' % self.args.firmware_updater)
    self._ui = UI()
    self._template = OneScrollableSection(self._ui)
    self._template.SetTitle(_TEST_TITLE)
    self._ui.AppendCSS(_CSS)

  def UpdateFirmware(self):
    """Runs firmware updater.

    While running updater, it shows updater activity on factory UI.
    """
    p = Spawn(
      [self.args.firmware_updater, '--force', '--factory',
       '--update_ec' if self.args.update_ec else '--noupdate_ec',
       '--update_main' if self.args.update_main else '--noupdate_main',],
      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, log=True)
    for line in iter(p.stdout.readline, ''):
      logging.info(line.strip())
      self._template.SetState(Escape(line), append=True)

    if p.poll() != 0:
      self._ui.Fail('Firmware update failed: %d.' % p.returncode)
    else:
      self._ui.Pass()

  def runTest(self):
    threading.Thread(target=self.UpdateFirmware).start()
    self._ui.Run()
