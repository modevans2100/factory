#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# We need to inject mock objects to protected members of FactoryEntry:
# pylint: disable=W0212

"""Unit tests for fixture_entry factory test."""

import logging
import mox
import unittest

import factory_common # pylint: disable=W0611
from cros.factory.goofy.goofy_rpc import GoofyRPC
from cros.factory.test import dut
from cros.factory.test import factory
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.dut.link import DUTLink
from cros.factory.test.pytests import fixture_entry
from cros.factory.utils import sync_utils

class FakeArgs(object):
  def __init__(self, dargs):
    for (key, value) in dargs.iteritems():
      self.__dict__[key] = value


class FactoryEntryUnitTest(unittest.TestCase):
  def setUp(self):
    self.mox = mox.Mox()
    self.test = fixture_entry.FixtureEntry()

    self.mock_ui = self.mox.CreateMock(test_ui.UI)
    self.mock_template = self.mox.CreateMock(ui_templates.OneSection)

  def tearDown(self):
    self.mox.UnsetStubs()

  def testSetUpForStartTesting(self):
    mock_state = self.mox.CreateMock(GoofyRPC)

    self.mox.StubOutWithMock(factory, 'get_state_instance')
    self.mox.StubOutWithMock(test_ui, 'UI')
    self.mox.StubOutWithMock(ui_templates, 'OneSection')

    # for start testing
    factory.get_state_instance().AndReturn(mock_state)
    test_ui.UI().AndReturn(self.mock_ui)
    self.mock_ui.AppendCSS(mox.IsA(str))
    ui_templates.OneSection(self.mock_ui).AndReturn(self.mock_template)
    self.mock_template.SetTitle(fixture_entry._TITLE_START)

    self.mox.ReplayAll()

    self.test.args = FakeArgs({'start_fixture_tests': True,
                               'prompt_start': False,
                               'clear_device_data': True,
                               'timeout_secs': None})
    self.test.setUp()
    self.assertEqual(self.test._state, mock_state) # pylint: disable=W0212

    self.mox.VerifyAll()

  def testLocalEndFixtureBasedTest(self):
    self._testEndFixtureBasedTest(is_local=True)

  def testNonLocalEndFixtureBasedTest(self):
    self._testEndFixtureBasedTest(is_local=False)

  def _testEndFixtureBasedTest(self, is_local):
    mock_dut_link = self.mox.CreateMock(DUTLink)
    self.test._dut = dut.Create()
    self.test._dut.link = mock_dut_link
    mock_state = self.mox.CreateMock(GoofyRPC)
    self.test._state = mock_state # pylint: disable=W0212
    timeout_secs = 123
    self.test.args = FakeArgs({'start_fixture_tests': False,
                               'prompt_start': False,
                               'clear_device_data': True,
                               'timeout_secs': timeout_secs})
    self.test._ui = self.mock_ui
    self.test._template = self.mock_template

    self.mox.StubOutWithMock(shopfloor, 'DeleteDeviceData')
    self.mox.StubOutWithMock(sync_utils, 'WaitFor')

    self.mock_ui.Run(blocking=False)
    self.mock_ui.BindKey(' ', mox.Func(callable))
    shopfloor.DeleteDeviceData(['serial_number', 'mlb_serial_number'],
                               optional=True)
    self.mock_template.SetState(mox.IsA(basestring))

    self.mock_template.SetState(mox.IsA(basestring))
    mock_dut_link.IsLocal().AndReturn(is_local)
    if not is_local:
      sync_utils.WaitFor(mox.IsA(type(lambda: None)), timeout_secs)

    self.mock_template.SetState(mox.IsA(basestring))
    mock_state.ScheduleRestart()

    self.mox.ReplayAll()

    self.test.runTest()

    self.mox.VerifyAll()

  def testStartFixtureBasedTest(self):
    mock_dut_link = self.mox.CreateMock(DUTLink)
    self.test._dut = dut.Create()
    self.test._dut.link = mock_dut_link
    self.test._ui = self.mock_ui
    self.test._template = self.mock_template
    timeout_secs = 123
    self.test.args = FakeArgs({'start_fixture_tests': True,
                               'prompt_start': False,
                               'clear_device_data': True,
                               'timeout_secs': timeout_secs})

    self.mox.StubOutWithMock(shopfloor, 'DeleteDeviceData')
    self.mox.StubOutWithMock(sync_utils, 'WaitFor')

    self.mock_ui.Run(blocking=False)
    self.mock_ui.BindKey(' ', mox.Func(callable))
    shopfloor.DeleteDeviceData(['serial_number', 'mlb_serial_number'],
                               optional=True)
    self.mock_template.SetState(mox.IsA(basestring))
    sync_utils.WaitFor(mock_dut_link.IsReady, timeout_secs)

    self.mox.ReplayAll()

    self.test.runTest()

    self.mox.VerifyAll()


if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO)
  unittest.main()