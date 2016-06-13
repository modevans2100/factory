# -*- coding: utf-8 -*-
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a lid angle test based on accelerometers.

There are two accelerometers in ChromeOS for lid angle calculation.
This test asks OP to turn lid angle into a desired angle and then
checks whether the lid angle is within some threshold.
Please notice this test requires the hinge to be in a horizontal plane.

Usage examples::

    OperatorTest(
        id='accelerometers_lid_angle',
        label_zh=u'上盖角度测试',
        pytest_name='accelerometers_lid_angle',
        dargs={'angle': 180,
               'tolerance': 5,
               'spec_offset': (128, 230),
               'spec_ideal_values': (0, 1024)})
"""

import logging
import math
import numpy as np
import threading
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test import dut
from cros.factory.test import test_ui
from cros.factory.test.args import Arg
from cros.factory.test.dut.accelerometer import AccelerometerException
from cros.factory.test.ui_templates import OneSection


_MSG_PROMPT_BUILDER = lambda a: test_ui.MakeLabel(
    'Please open the lid to %s degrees.' % a,
    u'请将上盖掀开到 %s 度。' % a)
_MSG_CONFIRM_BUILDER = lambda a: test_ui.MakeLabel(
    'Confirm %s degrees' % a,
    u'确认掀开到 %s 度' % a)
_MSG_CHECKING = test_ui.MakeLabel(
    'Checking angle...',
    u'正在确认角度……')

_ID_PROMPT = 'prompt'
_ID_CONFIRM_BUTTON = 'confirm-button'

_EVENT_CONFIRM = 'confirm'

_HTML_PROMPT = """
<div id="%s" class="prompt"></div>
<button id="%s" class="confirm-button" onclick="test.sendTestEvent(\'%s\')">
</button>
""" % (_ID_PROMPT, _ID_CONFIRM_BUTTON, _EVENT_CONFIRM)

_HTML_CHECKING = '<div class="status">%s</div>' % _MSG_CHECKING

_CSS = """
.prompt {
  font-size: 2em;
  margin: 0.2em 0 0.8em;
}
.confirm-button {
  font-size: 4em;
  padding: 0.5em 1em;
  margin: 0 auto;
  width: 90%;
  height: 60%;
  line-height: 1.2;
}
.status {
  width: 100%;
  line-height: 3em;
  font-size: 4em;
  margin-top: 1em;
  background: #ccc;
}
"""

_JS = """
window.onkeydown = function(event) {
  if (event.keyCode == 32) {  // space
    test.sendTestEvent('%s');
  }
}
""" % _EVENT_CONFIRM


class AccelerometersLidAngleTest(unittest.TestCase):
  ARGS = [
      Arg('angle', int, 'The target lid angle to test.',
          default=180, optional=True),
      Arg('tolerance', int, 'The tolerance ',
          default=5, optional=True),
      Arg('capture_count', int,
          'How many times to capture the raw data to '
          'calculate the lid angle.', default=20, optional=True),
      Arg('spec_offset', tuple,
          'A tuple of two integers, ex: (128, 230) '
          'indicating the tolerance for the digital output of sensors under '
          'zero gravity and one gravity. Those values are vendor-specific '
          'and should be provided by the vendor.', optional=False),
      Arg('spec_ideal_values', tuple,
          'A tuple of two integers, ex: (0, 1024) indicating the ideal value '
          'of digital output corresponding to 0G and 1G, respectively. For '
          'example, if a sensor has a 12-bit digital output and -/+ 2G '
          'detection range so the sensitivity is 1024 count/G. The value '
          'should be provided by the vendor.', optional=False),
      Arg('sample_rate_hz', int,
          'The sample rate in Hz to get raw data from '
          'accelerometers.', default=20, optional=True),
      Arg(
          'resolution', dict,
          'Keys: the position of the accelerometer. For example: "base" or "lid".'
          'Values: The number of bits in the accelerometer to store the output number.'
          'For example: 12 or 16. A example for resolution: {"base": 16, "lid": 16}',
          optional=False),
  ]

  def setUp(self):
    self.dut = dut.Create()
    self.lock = threading.Lock()
    self.ui = test_ui.UI()
    self.template = OneSection(self.ui)
    self.ui.AppendCSS(_CSS)
    self.template.SetState(_HTML_PROMPT)
    self.ui.RunJS(_JS)
    self.ui.SetHTML(_MSG_PROMPT_BUILDER(self.args.angle), id=_ID_PROMPT)
    self.ui.SetHTML(_MSG_CONFIRM_BUILDER(self.args.angle),
                    id=_ID_CONFIRM_BUTTON)
    self.ui.AddEventHandler(_EVENT_CONFIRM, self.StartTest)

    # Initializes an accelerometer utility class.
    self.accelerometers_locations = ['base', 'lid']
    self.accelerometers = {}
    for location in self.accelerometers_locations:
      self.accelerometers[location] = self.dut.accelerometer.GetController(
          self.args.spec_offset,
          self.args.spec_ideal_values,
          self.args.sample_rate_hz,
          location,
          self.args.resolution[location]
      )

  def _CalculateLidAngle(self):
    """ Calculate the lid angle based on the two accelerometers (base/lid).

    When the lid angle is 180 degrees and the keyboard is on a horizontal
    plane in front of an user, the standard orientation of both
    accelerometers is:
      +X axis is aligned with the hinge and pointing to the right.
      +Y axis is in the same plane as the keyboard pointing towards the
         top of the screen.
      +Z axis is perpendicular to the keyboard, pointing out of the keyboard.

    This orientation is used in kernel 3.18 and later, previous kernel
    might use different orientation. It's also used in Android and is defined
    in the w3 spec: http://www.w3.org/TR/orientation-event/#description.
    """
    cal_data = {}
    for location in self.accelerometers_locations:
      try:
        cal_data[location] = (
            self.accelerometers[location].GetCalibratedDataAverage(
                self.args.capture_count))
      except AccelerometerException as err:
        logging.info(
            'Read %s calibrated data failed: %r.', location, err.args[0])
        return None

    # +X axis is aligned with the hinge.
    hinge_vec = [float(self.args.spec_ideal_values[1]), 0.0, 0.0]
    # The calulation requires hinge in a horizontal position.
    min_value = self.args.spec_ideal_values[0] - self.args.spec_offset[0]
    max_value = self.args.spec_ideal_values[0] + self.args.spec_offset[0]
    for location in self.accelerometers_locations:
      if not min_value <= cal_data[location]['in_accel_x'] <= max_value:
        self.ui.Fail('The hinge is not in a horizontal plane.')

    base_vec_flattened = [
        0.0,
        cal_data['base']['in_accel_y'],
        cal_data['base']['in_accel_z']]
    lid_vec_flattened = [
        0.0,
        cal_data['lid']['in_accel_y'],
        cal_data['lid']['in_accel_z']]

    # http://en.wikipedia.org/wiki/Dot_product#Geometric_definition
    # We use dot product and inverse Cosine to get the angle between
    # base_vec_flattened and lid_vec_flattened in degrees.
    angle_between_vectors = math.degrees(math.acos(
        np.dot(base_vec_flattened, lid_vec_flattened) /
        np.linalg.norm(base_vec_flattened) /
        np.linalg.norm(lid_vec_flattened)))

    # Based on the standare orientation described above, the sum of the
    # lid angle (between keyboard and screen) and angle_between_vectors
    # is 180 degrees. For example, when turning the lid angle to 180 degrees,
    # the orientation of two accelerometers is the same, hence
    # angle_between_vectors is 0 degrees.
    lid_angle = 180.0 - angle_between_vectors

    # http://en.wikipedia.org/wiki/Cross_product#Geometric_meaning
    # If the dot product of this cross product is normal, it means that the
    # shortest angle between |base| and |lid| was counterclockwise with
    # respect to the surface represented by |hinge| and this angle must be
    # reversed. That means the current lid angle is >= 180 degrees and the
    # value should be (360.0 - lid_angle), where lid_angle is always the
    # smaller angle between the keyboard and the screen.
    lid_base_cross_vec = np.cross(base_vec_flattened, lid_vec_flattened)
    if np.dot(lid_base_cross_vec, hinge_vec) > 0.0:
      return 360.0 - lid_angle
    else:
      return lid_angle

  def StartTest(self, _):
    # Only allow the first event handler to run. Otherwise, other threads could
    # be started, and Goofy will wait for all of them to complete before passing
    # or failing.
    if not self.lock.acquire(False):
      return
    self.template.SetState(_HTML_CHECKING)
    angle = self._CalculateLidAngle()
    if angle is None:
      self.ui.Fail('There is no calibration value for accelerometer in VPD.')
    else:
      logging.info('angle=%d', angle)
      if (angle > self.args.angle + self.args.tolerance or
          angle < self.args.angle - self.args.tolerance):
        self.ui.Fail('The lid angle is out of range: %d' % angle)
      else:
        self.ui.Pass()

  def runTest(self):
    self.ui.Run()
