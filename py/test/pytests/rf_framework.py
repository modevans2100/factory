# -*- coding: utf-8 -*-
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""RF test flow framework.

It defines common portion of various fixture involved tests.
"""

import threading

import factory_common  # pylint: disable=W0611
from cros.factory.event_log import EventLog
from cros.factory.test import factory
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.args import Arg


class RfFramework(object):
  ARGS = [
      Arg('category', str,
          'Describes what category it is, should be one of calibration,'
          'production, conductive or debug.'),
      Arg('parameters', list,
          'A list of regular expressions indicates parameters to download from'
          'shopfloor server.', default=list()),
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

  def DownloadParameters(self):
    """Downloads parameters from shopfloor."""
    raise NotImplementedError(
        'Called without implementing DownloadParameters')

  def setUp(self):
    self.event_log = EventLog.ForAutoTest()
    self.interactive_mode = False
    # Initiate an UI
    self.ui = test_ui.UI()
    # TODO(itspeter): Set proper title and context for initial screen.
    self.template = ui_templates.OneSection(self.ui)
    self.key_pressed = threading.Condition()
    self.ui.Run(blocking=False)

    if len(self.args.parameters) > 0:
      self.DownloadParameters()

    # Allowed user to apply fine controls in engineering_mode
    if self.ui.InEngineeringMode():
      # TODO(itspeter): expose more options in run-time.
      factory.console.debug('engineering mode detected.')

  def runTest(self):
    if self.args.pre_test_outside_shield_box:
      self.PreTestOutsideShieldBox()
    if self.args.pre_test_inside_shield_box:
      self.PreTestInsideShieldBox()
      # TODO(itspeter): Support multiple language in prompt.
      self.Prompt(
          'Precheck passed.<br>'
          'Please press SPACE key to continue after shield-box is closed.',
          force_prompt=True)

    # Primary test
    # TODO(itspeter): Blinking the keyboard indicator.
    # TODO(itspeter): Timing on PrimaryTest().
    self.PrimaryTest()
    self.Prompt('Shield-box required testing finished.<br>'
                'Rest of the test can be executed without a shield-box.<br>'
                'Please press SPACE key to continue.',
                force_prompt=True)

    # Post-test
    if self.args.post_test:
      self.PostTest()

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
