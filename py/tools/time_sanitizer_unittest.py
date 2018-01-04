#!/usr/bin/env python
#
# Copyright 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import calendar
import logging
import mox
import os
import tempfile
import time
import unittest

from contextlib import contextmanager

import factory_common  # pylint: disable=W0611
from cros.factory.tools import time_sanitizer
from cros.factory.utils import file_utils


BASE_TIME = float(
    calendar.timegm(time.strptime('Sat Jun  9 00:00:00 2012')))

SECONDS_PER_DAY = 86400


# pylint: disable=protected-access
class TimeSanitizerTestBase(unittest.TestCase):

  def setUp(self):
    self.mox = mox.Mox()
    self.fake_time = self.mox.CreateMock(time_sanitizer.Time)
    self.fake_server_proxy = self.mox.CreateMockAnything()

    self.sanitizer = time_sanitizer.TimeSanitizer(
        self.state_file,
        monitor_interval_secs=30,
        time_bump_secs=60,
        max_leap_secs=SECONDS_PER_DAY)
    self.sanitizer._time = self.fake_time
    self.sanitizer._suppress_exceptions = False
    self.sanitizer._server_proxy = self.fake_server_proxy

  def run(self, result=None):
    with file_utils.TempDirectory(
        prefix='time_sanitizer_unittest.') as temp_dir:
      # pylint: disable=attribute-defined-outside-init
      self.state_file = os.path.join(temp_dir, 'state_file')
      super(TimeSanitizerTestBase, self).run(result)

  @contextmanager
  def Mock(self):
    """Context manager that sets up a mock, then runs the sanitizer once."""
    self.mox.ResetAll()
    yield
    self.mox.ReplayAll()
    self.sanitizer.RunOnce()
    self.mox.VerifyAll()

  def _ReadStateFile(self):
    return float(open(self.state_file).read().strip())


class TimeSanitizerBaseTimeTest(TimeSanitizerTestBase):

  def runTest(self):
    # pylint: disable=W0212
    # (access to protected members)
    with tempfile.NamedTemporaryFile() as f:
      self.assertEquals(os.stat(f.name).st_mtime,
                        time_sanitizer.GetBaseTimeFromFile(f.name))
    self.assertEquals(
        None,
        time_sanitizer.GetBaseTimeFromFile('/some-nonexistent-file'))


class TimeSanitizerFactoryServer(TimeSanitizerTestBase):

  def _RunWithServerUnavailable(self):
    """Simulate trying to contact the factory server but failing."""
    self.mox.ResetAll()
    self.fake_server_proxy.GetServerProxy(timeout=5).AndRaise(
        OSError())
    self.mox.ReplayAll()

    self.assertRaises(OSError, self.sanitizer.SyncWithFactoryServer)
    self.assertFalse(os.path.exists(self.state_file))
    self.mox.VerifyAll()

  def _RunWithServer(self, server_time, adjust):
    """Simulate successfully contacting the factory server.

    Args:
      server_time: The time to be reported by the factory server.
      adjust: Whether we expect that the sanitizer will actually adjust
        the time.
    """
    self.mox.ResetAll()
    proxy = self.mox.CreateMockAnything()
    self.fake_time.Time().AndReturn(BASE_TIME)
    self.fake_server_proxy.GetServerProxy(timeout=5).AndReturn(proxy)
    proxy.GetTime().AndReturn(server_time)
    self.fake_time.Time().AndReturn(BASE_TIME)
    if adjust:
      self.fake_time.SetTime(server_time)
    self.mox.ReplayAll()

    self.assertEquals(adjust, self.sanitizer.SyncWithFactoryServer())
    self.mox.VerifyAll()

  def testPastServer(self):
    self._RunWithServerUnavailable()

    # Now factory server is available,
    # but time is earlier than the BASE_TIME.  No adjustment.
    self._RunWithServer(BASE_TIME - 10, False)
    self.assertEquals(BASE_TIME, self._ReadStateFile())

  def testFuturefloor(self):
    self._RunWithServerUnavailable()

    # Now factory server is available,
    # and time is later than the BASE_TIME.  Adjust the time.
    self._RunWithServer(BASE_TIME + 10, True)
    self.assertEquals(BASE_TIME + 10, self._ReadStateFile())


class TimeSanitizerTest(TimeSanitizerTestBase):

  def runTest(self):
    with self.Mock():
      self.fake_time.Time().AndReturn(BASE_TIME)
    self.assertEquals(BASE_TIME, self._ReadStateFile())

    # Now move forward 1 second, and then forward 0 seconds.  Should
    # be fine.
    for _ in xrange(2):
      with self.Mock():
        self.fake_time.Time().AndReturn(BASE_TIME + 1)
      self.assertEquals(BASE_TIME + 1, self._ReadStateFile())

    # Now move forward 2 days.  This should be considered hosed, so
    # the time should be bumped up by time_bump_secs (120).
    with self.Mock():
      self.fake_time.Time().AndReturn(BASE_TIME + 2 * SECONDS_PER_DAY)
      self.fake_time.SetTime(BASE_TIME + 61)
    self.assertEquals(BASE_TIME + 61, self._ReadStateFile())

    # Move forward a bunch.  Fine.
    with self.Mock():
      self.fake_time.Time().AndReturn(BASE_TIME + 201.5)
    self.assertEquals(BASE_TIME + 201.5, self._ReadStateFile())

    # Jump back 20 seconds.  Not fine!
    with self.Mock():
      self.fake_time.Time().AndReturn(BASE_TIME + 181.5)
      self.fake_time.SetTime(BASE_TIME + 261.5)
    self.assertEquals(BASE_TIME + 261.5, self._ReadStateFile())


if __name__ == '__main__':
  logging.basicConfig(level=logging.DEBUG)
  unittest.main()
