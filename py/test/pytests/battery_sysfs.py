# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A hardware test for checking battery existence and its basic status.

Description
-----------
This test checks the battery existence and its status like cycle count,
wear level, and health status.

Test Procedure
--------------
This is an automated test without user interaction.

Dependency
----------
Depend on the sysfs driver to read information from the battery.

Examples
--------
To perform a battery test, add this in test list::

  {
    "pytest_name": "battery_sysfs",
    "args": {
      "maximum_cycle_count": 10,
      "percent_battery_wear_allowed": 5
    }
  }

To disable max cycle count check, set ``maximum_cycle_count`` to ``-1``.
To disable wear level check, set ``percent_battery_wear_allowed`` to ``-1``.
"""

import unittest

from cros.factory.device import device_utils
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg


class SysfsBatteryTest(unittest.TestCase):
  """Checks battery status."""
  ARGS = [
      Arg('maximum_cycle_count', int,
          'Maximum cycle count allowed to pass test', default=10),
      Arg('percent_battery_wear_allowed', int,
          'Maximum percent battery wear allowed to pass test', default=5),
  ]

  def setUp(self):
    self._power = device_utils.CreateDUTInterface().power

  def runTest(self):
    success = False
    msg = ''
    wearAllowedPct = self.args.percent_battery_wear_allowed
    wearPct = None
    power = self._power

    battery_present = power.CheckBatteryPresent()
    if not battery_present:
      msg = 'Cannot find battery path'
    elif power.GetChargePct() is None:
      msg = 'Cannot get charge percentage'
    elif 0 <= wearAllowedPct < 100:
      wearPct = power.GetWearPct()
      if wearPct is None:
        msg = 'Cannot get wear percentage'
      elif wearPct > wearAllowedPct:
        msg = 'Battery is over-worn: %d%%' % wearPct
      else:
        success = True
    else:
      success = True

    if battery_present:
      cycleCount = power.GetBatteryCycleCount()
      if success and self.args.maximum_cycle_count >= 0:
        if cycleCount > self.args.maximum_cycle_count:
          msg = 'Battery cycle count is too high: %d' % cycleCount
          success = False

      testlog.LogParam('battery_sysfs_info', power.GetInfoDict())

    self.assertTrue(success, msg)
