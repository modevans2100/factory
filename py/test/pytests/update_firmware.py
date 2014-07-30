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

from cros.factory.system import vpd
from cros.factory.test.args import Arg
from cros.factory.test.event import Event
from cros.factory.test.test_ui import Escape, MakeLabel, UI
from cros.factory.test.ui_templates import OneScrollableSection
from cros.factory.utils.process_utils import Spawn

_TEST_TITLE = MakeLabel('Update Firmware', u'更新韧体')
_CSS = '#state {text-align:left;}'


class UpdateFirmwareTest(unittest.TestCase):
  ARGS = [
    Arg('firmware_updater', str, 'Full path of chromeos-firmwareupdate.',
        default='/usr/local/factory/board/chromeos-firmwareupdate'),
    Arg('update_ec', bool, 'Update embedded firmware.', default=True),
    Arg('update_main', bool, 'Update main firmware.', default=True),
    Arg('apply_customization_id', bool,
        'Update root key based on the customization_id stored in VPD.',
        default=False, optional=True),
    Arg('mode', str, 'Firmware updater mode.',
        default='factory', optional=True),
    Arg('override_write_protect_value', int,
        'The value to override write protection state.'
        'Use 0 to override the state to False and 1 to override the state '
        'to True, respectively.',
        default=None, optional=True),
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
    # Remove /tmp/chromeos-firmwareupdate-running if the process
    # doesn't seem to be alive anymore.  (http://crosbug.com/p/15642)
    LOCK_FILE = '/tmp/chromeos-firmwareupdate-running'
    if os.path.exists(LOCK_FILE):
      process = Spawn(['pgrep', '-f', 'chromeos-firmwareupdate'],
                      call=True, log=True, read_stdout=True)
      if process.returncode == 0:
        # Found a chromeos-firmwareupdate alive.
        self._ui.Fail('Lock file %s is present and firmware update already '
                      'running (PID %s)' % (
            LOCK_FILE, ', '.join(process.stdout_data.split())))
        return
      logging.warn('Removing %s', LOCK_FILE)
      os.unlink(LOCK_FILE)

    firmware_updater_command = [
        self.args.firmware_updater, '--force', '--mode', self.args.mode,
        '--update_ec' if self.args.update_ec else '--noupdate_ec',
        '--update_main' if self.args.update_main else '--noupdate_main']

    if self.args.apply_customization_id:
      customization_id = vpd.ro.get("customization_id")
      if customization_id is None:
        self._ui.Fail('Customization_id not found in VPD.')
        return
      if not self.args.update_main:
        self._ui.Fail(
            'Main firmware must be updated when apply customization_id.')
        return
      firmware_updater_command += ['--customization_id', customization_id]

    if self.args.override_write_protect_value is not None:
      firmware_updater_command += [
          '--wp', str(self.args.override_write_protect_value)]

    p = Spawn(firmware_updater_command, stdout=subprocess.PIPE,
              stderr=subprocess.STDOUT, log=True)
    for line in iter(p.stdout.readline, ''):
      logging.info(line.strip())
      self._template.SetState(Escape(line), append=True)

    # Updates system info so EC and Firmware version in system info box
    # are correct.
    self._ui.event_client.post_event(Event(Event.Type.UPDATE_SYSTEM_INFO))

    if p.poll() != 0:
      self._ui.Fail('Firmware update failed: %d.' % p.returncode)
    else:
      self._ui.Pass()

  def runTest(self):
    threading.Thread(target=self.UpdateFirmware).start()
    self._ui.Run()
