#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test battery communication.

The test uses cros.factory.test.dut.power to get battery design capacity.
"""

import logging
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test.args import Arg
from cros.factory.test import dut


class BoardBatteryTest(unittest.TestCase):
  """Tests board battery communication."""
  ARGS = [
      Arg('design_capacity_range', tuple,
          'Expected battery design capacity range in mAh.',
          default=(1000, 10000)),
  ]

  def setUp(self):
    self.dut = dut.Create()

  def runTest(self):
    lower, upper = self.args.design_capacity_range
    capacity = self.dut.power.GetBatteryDesignCapacity()
    logging.info('Get battery design capacity: %d', capacity)
    self.assertTrue(
        lower <= capacity <= upper,
        'Battery design capacity %d out of range: %s' % (
            capacity, str(self.args.design_capacity_range)))