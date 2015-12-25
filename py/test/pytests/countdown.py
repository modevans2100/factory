# -*- coding: utf-8 -*-
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A count down UI for run-in test.

It shows count down and system loads for run-in period. It also alarms if
there's any abnormal status detected during run-in.
"""

import os
import time
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test.event_log import Log
from cros.factory.test import dut
from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.test.args import Arg
from cros.factory.utils import time_utils


class CountDownTest(unittest.TestCase):
  """A countdown test that monitors and logs various system status."""

  ARGS = [
      Arg('title_en', (str, unicode), 'English title.', 'Countdown'),
      Arg('title_zh', (str, unicode), 'Chinese title.', u'倒數計時'),
      Arg('position_top_right', bool,
          'A workaround for some machines on which graphics test would overlay '
          'countdown info.', False),
      Arg('duration_secs', int, 'Duration of time to countdown.'),
      Arg('log_interval', int,
          'Interval of time in seconds to log system status.', 120),
      Arg('ui_update_interval', int,
          'Interval of time in seconds to update system status on UI.', 10),
      Arg('grace_secs', int,
          'Grace period before starting abnormal status detection.', 120,
          optional=True),
      Arg('temp_max_delta', int,
          'Allowed difference between current and last temperature of a '
          'sensor.', None, optional=True),
      Arg('temp_criteria', (list, tuple),
          'A list of rules to check that temperature is under the given range, '
          'rule format: (name, temp_index, warning_temp, critical_temp)', [],
          optional=True),
      Arg('relative_temp_criteria', (list, tuple),
          'A list of rules to check the difference between two temp sensors, '
          'rule format: (relation, first_index, second_index, max_diff). '
          'relation is a text output with warning messages to describe the two '
          'temp sensors in the rule', [], optional=True),
      Arg('fan_min_expected_rpm', int, 'Minimum fan rpm expected', None,
          optional=True)]

  def FormatSeconds(self, secs):
    hours = int(secs / 3600)
    minutes = int((secs / 60) % 60)
    seconds = int(secs % 60)
    return '%02d:%02d:%02d' % (hours, minutes, seconds)

  def UpdateTimeAndLoad(self):
    self._ui.SetHTML(
        self.FormatSeconds(self._elapsed_secs),
        id='cd-elapsed-time')
    self._ui.SetHTML(
        self.FormatSeconds(self._remaining_secs),
        id='cd-remaining-time')
    self._ui.SetHTML(
        ' '.join(open('/proc/loadavg').read().split()[0:3]),
        id='cd-system-load')

  def UpdateUILog(self, sys_status):
    log_items = [time_utils.TimeString(),
                 'Temperatures: %s' % sys_status.temperatures,
                 'Fan RPM: %s' % sys_status.fan_rpm]
    log_str = '.  '.join(log_items)
    self._verbose_log.write(log_str + os.linesep)
    self._verbose_log.flush()
    self._ui.AppendHTML('%s<br>' % log_str, id='cd-log-panel')
    self._ui.RunJS('$("cd-log-panel").scrollTop = '
                   '$("cd-log-panel").scrollHeight;')

  def UpdateLegend(self, sensor_names):
    for idx in xrange(len(sensor_names)):
      self._ui.AppendHTML('<div class="cd-legend-item">[%d] %s</div>' %
                          (idx, sensor_names[idx]),
                          id='cd-legend-item-panel')
    if sensor_names:
      self._ui.RunJS('$("cd-legend-panel").style.display = "block";')

  def DetectAbnormalStatus(self, status, last_status):
    def GetTemperature(index):
      try:
        return status.temperatures[index]
      except IndexError:
        return None

    warnings = []

    if self.args.temp_max_delta:
      if len(status.temperatures) != len(last_status.temperatures):
        warnings.append(
            'Number of temperature sensors differ (current: %d, last: %d) ' %
            (len(status.temperatures), len(last_status.temperatures)))
      for index, (current, last) in enumerate(
          zip(status.temperatures, last_status.temperatures)):
        # Ignore the case when both are None since it could just mean the
        # sensor doesn't exist. If only one of them is None, then there
        # is a problem.
        if last is None and current is None:
          continue
        elif last is None or current is None:
          warnings.append(
              'Cannot read temperature index %d (current: %r, last: %r)' %
              (index, current, last))
        elif abs(current - last) > self.args.temp_max_delta:
          warnings.append(
              'Temperature index %d delta over %d (current: %d, last: %d)' %
              (index, self.args.temp_max_delta, current, last))

    for name, index, warning_temp, critical_temp in self.args.temp_criteria:
      temp = GetTemperature(index)
      if temp is None:
        warnings.append('%s temperature unavailable' % name)
      elif temp >= critical_temp:
        warnings.append('%s over critical temperature (now: %d, critical: %d)' %
                        (name, temp, critical_temp))
      elif temp >= warning_temp:
        warnings.append('%s over warning temperature (now: %d, warning: %d)' %
                        (name, temp, warning_temp))

    for (relation, first_index, second_index,
         max_diff) in self.args.relative_temp_criteria:
      first_temp = GetTemperature(first_index)
      second_temp = GetTemperature(second_index)
      if first_temp is None or second_temp is None:
        unavailable_index = []
        if first_temp is None:
          unavailable_index.append(first_index)
        if second_temp is None:
          unavailable_index.append(second_index)
        warnings.append(
            'Cannot measure temperature difference between %s: '
            'temperature %s unavailable' %
            (relation, ', '.join(unavailable_index)))
      else:
        if abs(first_temp - second_temp) > max_diff:
          warnings.append('Temperature difference between %s over %d '
                          '(first: %d, second: %d)' %
                          (relation, max_diff, first_temp, second_temp))

    if self.args.fan_min_expected_rpm:
      for i, ith_fan_rpm in enumerate(status.fan_rpm):
        if ith_fan_rpm < self.args.fan_min_expected_rpm:
          warnings.append('Fan %d rpm %d less than min expected %d' %
                          (i, ith_fan_rpm, self.args.fan_min_expected_rpm))

    in_grace_period = self._elapsed_secs < self.args.grace_secs
    if warnings:
      Log('warnings', elapsed_secs=self._elapsed_secs,
          in_grace_period=in_grace_period, warnings=warnings)
      if not in_grace_period:
        for w in warnings:
          factory.console.warn(w)

  def setUp(self):
    self._dut = dut.Create()

  def runTest(self):
    # Allow attributes to be defined outside __init__
    # pylint: disable=W0201

    self._ui = test_ui.UI()
    self._ui.Run(blocking=False)
    self._ui.SetHTML(self.args.title_en, id='cd-title-en')
    self._ui.SetHTML(self.args.title_zh, id='cd-title-zh')

    # A workaround for some machines in which graphics test would
    # overlay countdown info.
    if self.args.position_top_right:
      self._ui.RunJS('document.getElementById("cd-container").className'
                     ' = "float-right";')

    self._verbose_log = factory.get_verbose_log_file()
    self._start_secs = time.time()
    self._elapsed_secs = 0
    self._remaining_secs = self.args.duration_secs
    self._next_log_time = 0
    self._next_ui_update_time = 0
    last_status = self._dut.status.Snapshot()

    try:
      self.UpdateLegend(self._dut.thermal.GetTemperatureSensorNames())
    except NotImplementedError:
      pass

    # Loop until count-down ends.
    while self._remaining_secs >= 0:
      self.UpdateTimeAndLoad()

      current_time = time.time()
      if (current_time >= self._next_log_time or
          current_time >= self._next_ui_update_time):
        sys_status = self._dut.status.Snapshot()

      if current_time >= self._next_log_time:
        Log('system_status', elapsed_secs=self._elapsed_secs,
            **sys_status.__dict__)
        self.DetectAbnormalStatus(sys_status, last_status)
        last_status = sys_status
        self._next_log_time = current_time + self.args.log_interval

      if current_time >= self._next_ui_update_time:
        self.UpdateUILog(sys_status)
        self._next_ui_update_time = current_time + self.args.ui_update_interval

      time.sleep(1)
      self._elapsed_secs = time.time() - self._start_secs
      self._remaining_secs = round(self.args.duration_secs - self._elapsed_secs)
