#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.goofy.plugins import plugin_controller


def SyncDate(dut=None):
  """Sync DUT datetime with station.

  Args:
    :type dut: cros.factory.device.board.DeviceBoard
  """

  if not dut:
    dut = device_utils.CreateDUTInterface()

  if not dut.link.IsLocal():
    now = datetime.datetime.utcnow()
    # set DUT time
    dut.CheckCall(['date', '-u', '{:%m%d%H%M%Y.%S}'.format(now)], log=True)


def SyncTimeWithShopfloorServer():
  """Sync time with shopfloor server.

  Returns: False if TimeSanitizer is not running.
  """
  time_sanitizer = plugin_controller.GetPluginRPCProxy('time_sanitizer')
  if time_sanitizer is not None:
    time_sanitizer.SyncTimeWithShopfloorServer()
    return True
  else:
    return False
