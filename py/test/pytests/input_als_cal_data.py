# -*- mode: python; coding: utf-8 -*-
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import unittest

from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test import utils
from cros.factory.test.args import Arg
from cros.factory.utils.process_utils import Spawn

_EVENT_ALS_INPUT = 'ALS-Input'
_JS_ALS_CAL_DATA = '''
    var element = document.getElementById("inputValue");
    element.focus();
'''

_MESSAGE_WRITING = (lambda als:
    test_ui.MakeLabel('Writing ALS calibration value: %d' % als,
                      '写ALS值: %d' % als,
                      'als-font-size'))

_MESSAGE_WRITING_CSS = '.als-font-size {font-size: 2em;}'

class InputAlsCalData(unittest.TestCase):
  '''Display a input box for operator to enter ALS calibration value and
  write it in RO VPD als_cal_data field.'''

  ARGS = [
    Arg('min_value', int, 'Min value for ALS calibration value.', default=0),
    Arg('max_value', int, 'Max value for ALS calibration value.', default=25),
  ]

  def HandleInputValue(self, event):
    def SetError(label_en, label_zh=None):
      logging.info('Input error: %r', label_en)
      self.ui.SetHTML(test_ui.MakeLabel(label_en, label_zh),
                      id='inputError')

    als_cal_data = event.data.strip()
    logging.debug('Input value: %s', als_cal_data)
    if not als_cal_data:
      return SetError('No input', u'未输入')

    try:
      als_cal_data = int(als_cal_data)
      assert als_cal_data >= self.args.min_value
      assert als_cal_data <= self.args.max_value
      if als_cal_data != self._als_cal_data:
        self.template.SetState(_MESSAGE_WRITING(als_cal_data))
        Spawn(['vpd', '-i', 'RO_VPD', '-s', 'als_cal_data=%d' % als_cal_data],
              check_call=True, log=True)
    except ValueError:
      return SetError('Invalid data format', u'资料格式错误')
    except AssertionError:
      return SetError('Invalid number', u'无效的数字')
    except:  # pylint: disable=W0702
      logging.exception('Write als_cal_data failed')
      return SetError(utils.FormatExceptionOnly())

    self.ui.Pass()

  def setUp(self):
    self.ui = test_ui.UI()
    self.ui.AppendCSS(_MESSAGE_WRITING_CSS)
    self.template = ui_templates.OneSection(self.ui)
    self._als_cal_data = int(Spawn(
        ['vpd', '-i', 'RO_VPD', '-g', 'als_cal_data'],
        check_output=True).stdout_data)
    self.template.SetTitle(test_ui.MakeLabel('Input ALS calibration value',
                                             u'输入 ALS 校正资料'))
    self.template.SetState(
        test_ui.MakeLabel(
            'Please input ALS calibration value and press ENTER.',
            u'请输入 ALS 校正资料後按下 ENTER') + '<br>' +
        '<input id="inputValue" type="input" value="%d">' % self._als_cal_data +
        '<br><p id="inputError" class="test-error">')
    self.ui.AddEventHandler(_EVENT_ALS_INPUT, self.HandleInputValue)
    self.ui.BindKeyJS(
        '\r',
        'window.test.sendTestEvent('
        '  "%s", document.getElementById("inputValue").value)' %
        _EVENT_ALS_INPUT)
    self.ui.AddEventHandler('input_value', self.HandleInputValue)

  def runTest(self):
    self.ui.RunJS(_JS_ALS_CAL_DATA)
    self.ui.Run()
