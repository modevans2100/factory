#!/usr/bin/python -u
# -*- coding: utf-8 -*-
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The main factory flow that runs the presenter-side of factory tests."""

import argparse
import logging
import syslog

import factory_common  # pylint: disable=W0611
from cros.factory.goofy import test_environment
from cros.factory.goofy.goofy_base import GoofyBase
from cros.factory.goofy.link_manager import DUTLinkManager
from cros.factory.goofy.ui_app_controller import UIAppController
from cros.factory.test import factory
from cros.factory.utils import jsonrpc_utils
from cros.factory.utils import sys_utils


class GoofyPresenter(GoofyBase):
  """Presenter side of Goofy.

  Note that all methods in this class must be invoked from the main
  (event) thread.  Other threads, such as callbacks and TestInvocation
  methods, should instead post events on the run queue.

  Properties:
    link_manager: The DUTLinkManager for this invocation of Goofy.
    ui_app_controller: UIAppController instance used to communicate with
        UI presenter app.
    dut_ips: The list of DUT ips.
    dut_dongle_mac_address: The dictionary maping the ip address of DUT to
        the dongle mac address of it.
  """

  def __init__(self):
    super(GoofyPresenter, self).__init__()

    self.args = self.ParseOptions()

    self.ui_app_controller = UIAppController(connect_hook=self.UIConnected)
    self.dut_ips = []
    self.dut_dongle_mac_address = {}

    if sys_utils.InCrOSDevice():
      self.env = test_environment.DUTEnvironment()
      self.env.has_sockets = self.ui_app_controller.HasWebSockets
    else:
      self.env = test_environment.FakeChrootEnvironment()
    self.env.launch_chrome()

    self.link_manager = DUTLinkManager(
        check_interval=1,
        connect_hook=self.DUTConnected,
        disconnect_hook=self.DUTDisconnected,
        methods={'StartCountdown': self.UIAppCountdown,
                 'UpdateStatus': self.UpdateStatus},
        standalone=self.args.standalone)

  def ParseOptions(self):
    parser = argparse.ArgumentParser(description='Run Goofy presenter')
    parser.add_argument('--standalone', action='store_true',
                        help=('Assume the controller is running on the same '
                              'machines.'))
    return parser.parse_args()

  def RetryShowUI(self):
    if not self.dut_ips:
      return
    dut_ip = self.dut_ips[-1]
    if self.ui_app_controller.ShowUI(dut_ip,
                                     self.dut_dongle_mac_address[dut_ip]):
      return
    # The UI is still not ready. Retry again.
    self.run_enqueue(self.RetryShowUI)

  def DUTConnected(self, dut_ip, dongle_mac_address):
    self.dut_dongle_mac_address[dut_ip] = dongle_mac_address
    self.dut_ips.append(dut_ip)
    # If the UI web server is ready, show it.
    if self.ui_app_controller.ShowUI(dut_ip, dongle_mac_address):
      return
    # Well, it's probably not. Let's schedule a retry.
    self.run_enqueue(self.RetryShowUI)

  def DUTDisconnected(self, dut_ip):
    dongle_mac_address = self.dut_dongle_mac_address[dut_ip]
    self.ui_app_controller.ShowDisconnectedScreen(dongle_mac_address)
    self.dut_ips.remove(dut_ip)
    del self.dut_dongle_mac_address[dut_ip]

  def UIConnected(self):
    if self.dut_ips:
      dut_ip = self.dut_ips[-1]
      self.ui_app_controller.ShowUI(dut_ip, self.dut_dongle_mac_address[dut_ip])

  def UIAppCountdown(self, message, timeout_secs, timeout_message,
                     timeout_message_color):
    """Start countdown on the UI.

    Args:
      message: The text to show during countdown.
      timeout_secs: The timeout for countdown.
      timeout_message: The text to show when countdown eneds.
      timeout_message_color: The color of the text when countdown ends.
    """
    dut_ip = jsonrpc_utils.GetJSONRPCCallerIP()
    dongle_mac_address = self.dut_dongle_mac_address[dut_ip]
    self.ui_app_controller.StartCountdown(message,
                                          dongle_mac_address,
                                          timeout_secs,
                                          timeout_message,
                                          timeout_message_color)

  def UpdateStatus(self, all_pass):
    dut_ip = jsonrpc_utils.GetJSONRPCCallerIP()
    dongle_mac_address = self.dut_dongle_mac_address[dut_ip]
    self.ui_app_controller.UpdateStatus(dongle_mac_address, all_pass)

  def main(self):
    """Entry point for goofy_presenter instance."""
    syslog.openlog('goofy_presenter')
    syslog.syslog('GoofyPresenter (factory test harness) starting')
    self.link_manager.Start()
    self.run()

  def destroy(self):
    """Performs any shutdown tasks. Overrides base class method."""
    self.link_manager.Stop()
    self.ui_app_controller.Stop()
    super(GoofyPresenter, self).destroy()
    logging.info('Done destroying GoofyPresenter')


if __name__ == '__main__':
  factory.init_logging()
  GoofyPresenter.run_main_and_exit()