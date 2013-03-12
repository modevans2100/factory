# -*- coding: utf-8 -*-
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""RF test flow framework.

It defines common portion of various fixture involved tests.
"""

import logging
import os
import re
import threading
import time
import yaml

from contextlib import contextmanager
from xmlrpclib import Binary

import factory_common  # pylint: disable=W0611
from cros.factory import event_log
from cros.factory.goofy.goofy import CACHES_DIR
from cros.factory.rf.tools.csv_writer import WriteCsv
from cros.factory.test import factory
from cros.factory.test import leds
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test import utils
from cros.factory.test.args import Arg
from cros.factory.utils import net_utils

SHOPFLOOR_TIMEOUT_SECS = 10 # Timeout for shopfloor connection.
SHOPFLOOR_RETRY_INTERVAL_SECS = 10 # Seconds to wait between retries.

class RfFramework(object):
  NORMAL_MODE = 'Normal'
  DETAIL_PROMPT = 'Detail prompts'
  DETAIL_PROMPT_WITHOUT_EQUIPMENT = 'Detail prompts without equipment'

  ARGS = [
      Arg('category', str,
          'Describes what category it is, should be one of calibration,'
          'production, conductive or debug.'),
      Arg('config_file', str,
          'Describes where configuration locates.'),
      Arg('parameters', list,
          'A list of regular expressions indicates parameters to download from '
          'shopfloor server.', default=list()),
      Arg('calibration_target', str,
          'A path to calibration_target.', optional=True),
      Arg('blinking_pattern', list,
          'A list of blinking state that will be passed to Blinker for '
          'inside shield-box primary test. '
          'More details of format could be found under Blinker.__init__()',
          default=[(0b111, 0.10), (0b000, 0.10)], ),
      Arg('static_ip', str,
          'Static IP for the DUT; default to acquire one from DHCP.',
          default=None, optional=True),
      Arg('pre_test_outside_shield_box', bool,
          'True to execute PreTestOutsideShieldBox.',
          default=True),
      Arg('pre_test_inside_shield_box', bool,
          'True to execute PreTestInsideShieldBox.',
          default=True),
      Arg('post_test', bool,
          'True to execute PostTest.',
          default=True)
      ]

  def __init__(self, *args, **kwargs):
    super(RfFramework, self ).__init__(*args, **kwargs)
    self.config = None
    self.calibration_target = None
    self.field_to_record = dict()
    self.aux_logs = list()
    self.unique_identification = None

  def setUp(self):
    self.event_log = event_log.EventLog.ForAutoTest()
    self.caches_dir = os.path.join(CACHES_DIR, 'parameters')
    self.interactive_mode = False
    self.calibration_mode = False
    self.equipment_enabled = True
    self.mode = self.NORMAL_MODE
    # Initiate an UI
    self.ui = test_ui.UI()
    # TODO(itspeter): Set proper title and context for initial screen.
    self.template = ui_templates.OneSection(self.ui)
    self.key_pressed = threading.Condition()
    self.ui_thread = self.ui.Run(blocking=False)
    self.failures = []

    # Allowed user to apply fine controls in engineering_mode
    if self.ui.InEngineeringMode():
      factory.console.debug('engineering mode detected.')
      self.mode = self.SelectMode(
          'mode',
          [self.NORMAL_MODE, self.DETAIL_PROMPT_WITHOUT_EQUIPMENT,
           self.DETAIL_PROMPT])
      if self.mode == self.DETAIL_PROMPT:
        self.interactive_mode = True
      elif self.mode == self.DETAIL_PROMPT_WITHOUT_EQUIPMENT:
        self.interactive_mode = True
        self.equipment_enabled = False

    factory.console.info('mode = %s', self.mode)
    factory.console.info('interactive_mode = %s', self.interactive_mode)
    factory.console.info('equipment_enabled = %s', self.equipment_enabled)

  def runTest(self):
    self.unique_identification = self.GetUniqueIdentification()

    if self.args.pre_test_outside_shield_box:
      self.template.SetState('Preparing network.')
      self.PrepareNetwork()
      if len(self.args.parameters) > 0:
        self.template.SetState('Downloading parameters.')
        self.DownloadParameters(self.args.parameters)

      # Prepare additional parameters if we are in calibration mode.
      if self.args.category == 'calibration':
        self.calibration_mode = True
        self.template.SetState('Downloading calibration_target.')
        self.DownloadParameters([self.args.calibration_target])
        # Load the calibration_target
        with open(os.path.join(
            self.caches_dir, self.args.calibration_target), "r") as fd:
          self.calibration_target = yaml.load(fd.read())

        # Confirm if this DUT is in the list of targets.
        if self.unique_identification not in self.calibration_target:
          failure = 'DUT %r is not in the calibration_target' % (
              self.unique_identification)
          factory.console.info(failure)
          self.ui.Fail(failure)
          self.ui_thread.join()
        self.calibration_target = (
            self.calibration_target[self.unique_identification])
        factory.console.info('Calibration target=\n%s',
            self.calibration_target)

      # Load the main configuration.
      with open(os.path.join(
          self.caches_dir, self.args.config_file), "r") as fd:
        self.config = yaml.load(fd.read())

      self.template.SetState('Runing outside shield box test.')
      self.PreTestOutsideShieldBox()
      self.EnterFactoryMode()
      self.Prompt(
          'Procedure outside shield-box is completed.<br>'
          'Please press SPACE key to continue.',
          force_prompt=True)

    try:
      if self.args.pre_test_inside_shield_box:
        self.template.SetState('Preparing network.')
        self.PrepareNetwork()
        self.template.SetState('Runing pilot test inside shield box.')
        self.PreTestInsideShieldBox()
        # TODO(itspeter): Support multiple language in prompt.
        self.Prompt(
            'Precheck passed.<br>'
            'Please press SPACE key to continue after shield-box is closed.',
            force_prompt=True)

      # Primary test
      # TODO(itspeter): Timing on PrimaryTest().
      self.template.SetState('Runing primary test.')
      with leds.Blinker(self.args.blinking_pattern):
        self.PrimaryTest()
      # Save useful info to the CSV and eventlog.
      self.LogDetail()

      # Light all LEDs to indicates test is completed.
      leds.SetLeds(leds.LED_SCR|leds.LED_NUM|leds.LED_CAP)
      self.Prompt(
          'Shield-box required testing finished.<br>'
          'Rest of the test can be executed without a shield-box.<br>'
          'Please press SPACE key to continue.',
          force_prompt=True)
      leds.SetLeds(0)

      # Post-test
      if self.args.post_test:
        self.template.SetState('Preparing network.')
        self.PrepareNetwork()
        self.template.SetState('Runing post test.')
        self.PostTest()
        # Upload the aux_logs to shopfloor server.
        self.UploadAuxLogs(self.aux_logs)
    finally:
      self.ExitFactoryMode()

    # Fail the test if failure happened.
    if len(self.failures) > 0:
      self.ui.Fail('\n'.join(self.failures))
    self.ui.Pass()
    self.ui_thread.join()

  def PreTestOutsideShieldBox(self):
    """Placeholder for procedures outside the shield-box before primary test."""
    raise NotImplementedError(
        'Called without implementing PreTestOutsideShieldBox')

  def PreTestInsideShieldBox(self):
    """Placeholder for procedures inside the shield-box before primary test."""
    raise NotImplementedError(
        'Called without implementing PreTestInsideShieldBox')

  def PrimaryTest(self):
    """Placeholder for primary test."""
    raise NotImplementedError(
        'Called without implementing PrimaryTest')

  def PostTest(self):
    """Placeholder for prcedures after primary test."""
    raise NotImplementedError(
        'Called without implementing PostTest')

  def EnterFactoryMode(self):
    """Prepares factory specific environment."""
    raise NotImplementedError(
        'Called without implementing EnterFactoryMode')

  def ExitFactoryMode(self):
    """Exits factory specific environment.

    This function will be called when test exits."""
    raise NotImplementedError(
        'Called without implementing ExitFactoryMode')

  def GetUniqueIdentification(self):
    """Gets the unique identification for module to test."""
    raise NotImplementedError(
        'Called without implementing GetUniqueIdentification')

  def IsInRange(self, observed, threshold_min, threshold_max):
    """Returns True if threshold_min <= observed <= threshold_max.

    If either thresholds are None, then the comparison will always succeed."""
    if threshold_min is not None and observed < threshold_min:
      return False
    if threshold_max is not None and observed > threshold_max:
      return False
    return True

  def FormattedPower(self, power, format_str='%7.2f'):
    """Returns a formatted power while allowing power be a None."""
    return 'None' if power is None else (format_str % power)

  def CheckPower(self, measurement_name, power, threshold, prefix='Power'):
    '''Simple wrapper to check and display related messages.'''
    min_power, max_power = threshold
    if not self.IsInRange(power, min_power, max_power):
      failure = '%s for %r is %s, out of range (%s,%s)' % (
          prefix, measurement_name, self.FormattedPower(power),
          self.FormattedPower(min_power), self.FormattedPower(max_power))
      factory.console.info(failure)
      self.failures.append(failure)
    else:
      factory.console.info('%s for %r is %s',
          prefix, measurement_name, self.FormattedPower(power))

  def NormalizeAsFileName(self, token):
    return re.sub(r'\W+', '', token)

  def LogDetail(self):
    # Column names
    DEVICE_ID = 'device_id'
    DEVICE_SN = 'device_sn'
    MODULE_ID = 'module_id'
    PATH = 'path'
    FAILURES = 'failures'

    # log to event log.
    self.field_to_record[MODULE_ID] = self.unique_identification
    self.event_log.Log('measurement_details',
      **self.field_to_record)

    # additional fields that need to be added becasue they are recorded
    # in event log by default and we need them in csv as well.
    device_sn = shopfloor.get_serial_number() or 'MISSING_SN'
    path = os.environ.get('CROS_FACTORY_TEST_PATH')
    self.field_to_record[FAILURES] = self.failures
    self.field_to_record[DEVICE_SN] = device_sn
    self.field_to_record[DEVICE_ID] = event_log.GetDeviceId()
    self.field_to_record[PATH] = path
    csv_path = '%s_%s_%s.csv' % (
        time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()),
        self.NormalizeAsFileName(device_sn),
        self.NormalizeAsFileName(path))
    csv_path = os.path.join(factory.get_log_root(), 'aux', csv_path)
    utils.TryMakeDirs(os.path.dirname(csv_path))
    self.aux_logs.append(csv_path)
    WriteCsv(csv_path, [self.field_to_record],
             [MODULE_ID, DEVICE_SN, DEVICE_ID])
    factory.console.info('Details saved to %s', csv_path)

  @contextmanager
  def GetShopfloorConnection(
      self, timeout_secs=SHOPFLOOR_TIMEOUT_SECS,
      retry_interval_secs=SHOPFLOOR_RETRY_INTERVAL_SECS):
    """Yields an shopfloor client object.

    Try forever until a connection of shopfloor is established.

    Args:
      timeout_secs: Timeout for shopfloor connection.
      retry_interval_secs: Seconds to wait between retries.
    """
    while True:
      try:
        shopfloor_client = shopfloor.get_instance(
            detect=True, timeout=timeout_secs)
        yield shopfloor_client
        break
      except:  # pylint: disable=W0702
        exception_string = utils.FormatExceptionOnly()
        # Log only the exception string, not the entire exception,
        # since this may happen repeatedly.
        factory.console.info('Unable to sync with shopfloor server: %s',
                             exception_string)
      time.sleep(retry_interval_secs)

  def DownloadParameters(self, parameters):
    """Downloads parameters from shopfloor and saved to state/caches."""
    factory.console.info('Start downloading parameters...')
    with self.GetShopfloorConnection() as shopfloor_client:
      logging.info('Syncing time with shopfloor...')
      goofy = factory.get_state_instance()
      goofy.SyncTimeWithShopfloorServer()

      download_list = []
      for glob_expression in parameters:
        logging.info('Listing %s', glob_expression)
        download_list.extend(
            shopfloor_client.ListParameters(glob_expression))
      logging.info('Download list prepared:\n%s', '\n'.join(download_list))
      # Download the list and saved to caches in state directory.
      for filepath in download_list:
        utils.TryMakeDirs(os.path.join(
            self.caches_dir, os.path.dirname(filepath)))
        binary_obj = shopfloor_client.GetParameter(filepath)
        with open(os.path.join(self.caches_dir, filepath), 'wb') as fd:
          fd.write(binary_obj.data)
      # TODO(itspeter): Verify the signature of parameters.

  def UploadAuxLogs(self, file_paths, ignore_on_fail=False):
    """Attempts to upload arbitrary file to the shopfloor server."""
    with self.GetShopfloorConnection() as shopfloor_client:
      for file_path in file_paths:
        try:
          chunk = open(file_path, 'r').read()
          log_name = os.path.basename(file_path)
          factory.console.info('Uploading %s', log_name)
          start_time = time.time()
          shopfloor_client.SaveAuxLog(log_name, Binary(chunk))
          factory.console.info('Successfully synced %s in %.03f s',
              log_name, time.time() - start_time)
        except:  # pylint: disable=W0702
          if ignore_on_fail:
            factory.console.info(
                'Failed to sync with shopfloor for [%s], ignored',
                log_name)
          else:
            raise

  def PrepareNetwork(self):
    def ObtainIp():
      if self.args.static_ip is None:
        net_utils.SendDhcpRequest()
      else:
        net_utils.SetEthernetIp(self.args.static_ip)
      return True if net_utils.GetEthernetIp() else False

    _PREPARE_NETWORK_TIMEOUT_SECS = 30 # Timeout for network preparation.
    factory.console.info('Detecting Ethernet device...')
    net_utils.PollForCondition(condition=(
        lambda: True if net_utils.FindUsableEthDevice() else False),
        timeout=_PREPARE_NETWORK_TIMEOUT_SECS,
        condition_name='Detect Ethernet device')

    factory.console.info('Setting up IP address...')
    net_utils.PollForCondition(condition=ObtainIp,
        timeout=_PREPARE_NETWORK_TIMEOUT_SECS,
        condition_name='Setup IP address')

    factory.console.info('Network prepared. IP: %r', net_utils.GetEthernetIp())

  def SelectMode(self, title, choices):
    def GetSelectValue(dict_wrapper, event):
      # As python 2.x doesn't have a nonlocal keyword.
      # simulate the nonlocal by using a dict wrapper.
      select_value = event.data.strip()
      logging.info('Selected value: %s', select_value)
      dict_wrapper['select_value'] = select_value
      with self.key_pressed:
        self.key_pressed.notify()

    def GenerateRadioButtonsHtml(choices):
      '''Generates html snippet for the selection.

      First item will be selected by default.
      '''
      radio_button_html = ''
      for idx, choice in enumerate(choices):
        radio_button_html += (
            '<input name="select-value" type="radio" ' +
            ('checked ' if (idx == 0) else '') +
            'value="%s" id="choice_%d">' % (choice, idx) +
            '<label for="choice_%d">%s</label><br>' % (idx, choice))
      return radio_button_html

    dict_wrapper = dict()
    self.template.SetState(
        test_ui.MakeLabel(
            'Please select the %s and press ENTER.<br>' % title) +
        GenerateRadioButtonsHtml(choices) + '<br>&nbsp;'
        '<p id="select-error" class="test-error">&nbsp;')

    # Handle selected value when Enter pressed.
    self.ui.BindKeyJS(
        '\r',
        'window.test.sendTestEvent("select_value",'
        'function(){'
        '  choices = document.getElementsByName("select-value");'
        '  for (var i = 0; i < choices.length; ++i)'
        '    if (choices[i].checked)'
        '      return choices[i].value;'
        '  return "";'
        '}())')
    self.ui.AddEventHandler(
        'select_value',
        lambda event: GetSelectValue(dict_wrapper, event))
    with self.key_pressed:
      self.key_pressed.wait()
    self.ui.UnbindKey('\r')
    return dict_wrapper['select_value']

  def Prompt(self, prompt_str, key_to_wait=' ', force_prompt=False):
    """Displays a prompt to user and wait for a specific key.

    Args:
      prompt_str: The html snippet to display in the screen.
      key_to_wait: The specific key to wait from user, more details on
        BindKeyJS()'s docstring.
      force_prompt: A prompt call will be vaild if interactive_mode is True by
        default. Set force_prompt to True will override this behavior.
    """
    def KeyPressed():
      with self.key_pressed:
        self.key_pressed.notify()

    if not (force_prompt or self.interactive_mode):
      # Ignore the prompt request.
      return
    self.template.SetState(prompt_str)
    self.ui.BindKey(key_to_wait, lambda _: KeyPressed())
    with self.key_pressed:
      self.key_pressed.wait()
    self.ui.UnbindKey(key_to_wait)

  def RunEquipmentCommand(self, function, *args, **kwargs):
    """Wrapper for controling the equipment command.

    The function will only be called if self.equipment_enabled is True.
    """
    if self.equipment_enabled:
      return function(*args, **kwargs)
