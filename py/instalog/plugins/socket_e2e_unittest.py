#!/usr/bin/python2
#
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import print_function

import logging
import tempfile
import time
import unittest

import instalog_common  # pylint: disable=unused-import
from instalog import datatypes
from instalog import log_utils
from instalog import plugin_sandbox
from instalog import testing
from instalog.utils import net_utils


class TestSocket(unittest.TestCase):

  def setUp(self):
    self.core = testing.MockCore()
    self.hostname = 'localhost'
    self.port = net_utils.FindUnusedPort()

    # Create PluginSandbox for output plugin.
    output_config = {
        'hostname': 'localhost',
        'port': self.port,
        'timeout': 1}
    self.output_sandbox = plugin_sandbox.PluginSandbox(
        'output_socket', config=output_config, core_api=self.core)

    # Create PluginSandbox for input plugin.
    input_config = {
        'hostname': 'localhost',
        'port': self.port}
    self.input_sandbox = plugin_sandbox.PluginSandbox(
        'input_socket', config=input_config, core_api=self.core)

    # Start the plugins.  Input needs to start first; otherwise Output will
    # sleep for _FAILED_CONNECTION_INTERVAL.
    self.input_sandbox.Start(True)
    time.sleep(0.5)
    self.output_sandbox.Start(True)

    # Store a BufferEventStream.
    self.stream = self.core.GetStream(0)

  def tearDown(self):
    self.output_sandbox.Stop(True)
    self.input_sandbox.Stop(True)
    self.core.Close()

  def testOneEvent(self):
    self.stream.Queue([datatypes.Event({})])
    self.output_sandbox.Flush(2, True)
    self.assertEquals(self.core.emit_calls, [[datatypes.Event({})]])

  def testOneEventOneAttachment(self):
    with tempfile.NamedTemporaryFile() as f:
      f.write('XXXXXXXXXX')
      f.flush()
      event = datatypes.Event({}, {'my_attachment': f.name})
      self.stream.Queue([event])
      self.output_sandbox.Flush(2, True)
      self.assertEqual(1, len(self.core.emit_calls))
      event_list = self.core.emit_calls[0]
      self.assertEqual(1, len(event_list))
      self.assertEqual({}, event_list[0].payload)
      self.assertEqual(1, len(event_list[0].attachments))
      self.assertEqual('my_attachment', event_list[0].attachments.keys()[0])
      with open(event_list[0].attachments.values()[0]) as f:
        self.assertEqual('XXXXXXXXXX', f.read())


if __name__ == '__main__':
  log_utils.InitLogging(log_utils.GetStreamHandler(logging.INFO))
  unittest.main()