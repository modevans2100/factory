# -*- coding: utf-8 -*-
#
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Waits for a test executed by external fixture to finish.

This test will check and wait for /var/factory/external/<NAME> to appear.
If the file content is 'PASS' then test will be passed, otherwise it'll fail
with the content (including empty file).

The labels can use %(name)s that will be replaced by run_factory_external_name.

Example::

    # Test list
    OperatorTest(
        id='ExternalRF',
        pytest_name='wait_external_test',
        dargs={
            'run_factory_external_name': 'RF1',
            'label_en': 'Move DUT to station %(name)s',
            'label_zh': u'等待 %(name)s Test 執行中'
        })

    # External host
    path = '/var/factory/external/RF1'
    if success:
      self.dut.WriteFile(path, 'PASS')
    else:
      self.dut.WRiteFile(path, 'Failed with blah blah blah')
"""

import os
import time
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils


_EXTERNAL_DIR = '/run/factory/external'
_TEST_TITLE = test_ui.MakeLabel('Wait for external test', u'等待外部測試')
_ID_INSTRUCTION = 'external-test-instruction'
_ID_COUNTDOWN_TIMER = 'external-test-timer'

_CSS = """
.instruction-font-size {
  font-size: 2em;
}
"""

_HTML_EXTERNAL_TEST = """
<div id="%s" style="position: relative; width: 100%%; height: 60%%;"></div>
<div id="%s"></div>
""" % (_ID_INSTRUCTION, _ID_COUNTDOWN_TIMER)

# Usually external tests will take a long time to run so check duration can be
# longer.
_CHECK_PERIOD_SECS = 1


class WaitExternalTest(unittest.TestCase):
  """Wait for a test by external fixture to finish."""
  ARGS = [
      Arg('run_factory_external_name', str,
          'File name to check in /run/factory/external.', optional=False),
      Arg('msg_en', (str, unicode),
          'Instruction for running external test', optional=True),
      Arg('msg_zh', (str, unicode),
          'Instruction for running external test', optional=True)]

  def setUp(self):
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.template.SetTitle(_TEST_TITLE)
    self.template.SetState(_HTML_EXTERNAL_TEST)
    self.ui.AppendCSS(_CSS)
    self._name = self.args.run_factory_external_name
    info = {'name': self._name}
    instruction = [
        (self.args.msg_en or 'Please run external test: %(name)s') % info,
        (self.args.msg_zh or u'請執行外部測試: %(name)s') % info,
        'instruction-font-size']
    self.ui.SetHTML(test_ui.MakeLabel(*instruction), id=_ID_INSTRUCTION)
    self._file_path = os.path.join(
        _EXTERNAL_DIR, self.args.run_factory_external_name)
    self.RemoveFile(self._file_path)

  def FileExists(self):
    return os.path.exists(self._file_path)

  def MonitorResultFile(self):
    sync_utils.PollForCondition(
        poll_method=self.FileExists,
        poll_interval_secs=_CHECK_PERIOD_SECS,
        timeout_secs=None,
        condition_name='WaitForExternalFile')

    # Ideally external hosts should do atomic write, but since it's probably
    # done by 3rd party vendors with arbitrary implementation, so a quick and
    # simple solution is to wait for one more check period so the file should be
    # flushed.
    time.sleep(_CHECK_PERIOD_SECS)

    with open(self._file_path) as f:
      result = f.read().strip()

    if result.lower() == 'pass':
      self.ui.Pass()
    else:
      self.ui.Fail('Test %s completed with failure: %s' %
                   (self._name, result or 'unknown'))

  def RemoveFile(self, file_path):
    try:
      file_dir = os.path.dirname(file_path)
      file_utils.TryMakeDirs(file_dir)
      os.remove(file_path)
    except OSError:
      if os.path.exists(file_path) or not os.path.exists(file_dir):
        raise

  def runTest(self):
    process_utils.StartDaemonThread(target=self.MonitorResultFile)
    self.ui.Run()
