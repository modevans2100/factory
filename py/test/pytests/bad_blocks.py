#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''Tests the SSD by running the badblocks command.

The unused portion of the stateful partition is used.  (For instance,
on a device with a 32GB hard drive, cgpt reports that partition 1 is
about 25 GiB, but the size of the filesystem is only about 1 GiB.  We
run the test on the unused 24 GiB.)
'''

import logging
import re
import subprocess
import threading
import time
import unittest
from select import select

import factory_common  # pylint: disable=W0611

from cros.factory.event_log import EventLog
from cros.factory.test import factory
from cros.factory.test import ui_templates
from cros.factory.test import utils
from cros.factory.test.args import Arg
from cros.factory.test.test_ui import UI, Escape, MakeLabel
from cros.factory.utils.process_utils import Spawn

HTML = '''
<div id="bb-phase" style="font-size: 200%"></div>
<div id="bb-status" style="font-size: 150%"></div>
<div id="bb-progress"></div>
'''

class BadBlocksTest(unittest.TestCase):
  # SATA link speed, or None if unknown.
  sata_link_speed_mbps = None
  # /var/log/messages file.
  var_log_messages = None
  # Full path to the device.
  device_path = None

  ARGS = [
      Arg('device', str, 'The device on which to test.', default='sda'),
      Arg('max_bytes', int, 'Maximum size to test, in bytes.', optional=True),
      Arg('max_errors', int, 'Stops testing after the given number of errors.',
          default=20, optional=True),
      Arg('timeout_secs', (int, float), 'Timeout in seconds for progress lines',
          default=10),
      Arg('log_threshold_secs', (int, float),
          'If no badblocks output is detected for this long, log an error '
          'but do not fail',
          default=5),
      ]

  def setUp(self):
    self.ui = UI()
    self.template = ui_templates.TwoSections(self.ui)
    self.template.SetState(HTML)
    self.template.DrawProgressBar()
    self._event_log = EventLog.ForAutoTest()

  def runTest(self):
    thread = threading.Thread(target=self._CheckBadBlocks)
    thread.start()
    self.ui.Run()

  def tearDown(self):
    # Sync, so that any problems (like writing outside of our partition)
    # will show up sooner rather than later.
    self._LogSmartctl()
    Spawn(['sync'], call=True)

  def _CheckBadBlocks(self):
    try:
      self._CheckBadBlocksImpl()
    except:
      self.ui.Fail(utils.FormatExceptionOnly())
      raise
    else:
      self.ui.Pass()

  def _CheckBadBlocksImpl(self):
    self.assertFalse(utils.in_chroot(),
                     'badblocks test may not be run within the chroot')

    self.device_path = '/dev/%s' % self.args.device
    partition_path = '/dev/%s1' % self.args.device  # Always partition 1

    # Determine total length of the FS
    dumpe2fs = Spawn(['dumpe2fs', '-h', partition_path],
                     log=True, check_output=True).stdout_data
    logging.info('Filesystem info for  header:\n%s', dumpe2fs)

    fields = dict(re.findall(r'^(.+):\s+(.+)$', dumpe2fs, re.MULTILINE))
    fs_first_block = int(fields['First block'])
    fs_block_count = int(fields['Block count'])
    fs_block_size = int(fields['Block size'])

    # Grok cgpt data to find the partition size
    cgpt_start_sector, cgpt_sector_count = [
        int(Spawn(['cgpt', 'show', self.device_path, '-i', '1', flag],
                  log=True, check_output=True).stdout_data.strip())
        for flag in ('-b', '-s')]
    sector_size = int(
        open('/sys/class/block/%s/queue/hw_sector_size'
             % self.args.device).read().strip())

    # Could get this to work, but for now we assume that fs_block_size is a
    # multiple of sector_size.
    self.assertEquals(0, fs_block_size % sector_size,
                      'fs_block_size %d is not a multiple of sector_size %d' % (
                          fs_block_size, sector_size))

    first_unused_sector = (fs_first_block + fs_block_count) * (
        fs_block_size / sector_size)
    first_block = first_unused_sector + cgpt_start_sector
    sectors_to_test = cgpt_sector_count - first_unused_sector
    if self.args.max_bytes:
      sectors_to_test = min(sectors_to_test, self.args.max_bytes / sector_size)
    last_block = first_block + sectors_to_test - 1

    logging.info(', '.join(
        ['%s=%s' % (x, locals()[x])
         for x in ['fs_first_block', 'fs_block_count', 'fs_block_size',
                   'cgpt_start_sector', 'cgpt_sector_count',
                   'sector_size',
                   'first_unused_sector',
                   'sectors_to_test',
                   'first_block',
                   'last_block']]))

    self.assertTrue(last_block >= first_block)

    test_size_mb = '%.1f MiB' % (
        (last_block - first_block + 1) * sector_size / 1024.**2)

    self.template.SetInstruction(
        MakeLabel('Testing %s region of SSD' % test_size_mb,
                  '正在测试 %s 的 SSD 空间' % test_size_mb))

    # Kill any badblocks processes currently running
    Spawn(['killall', 'badblocks'], ignore_stderr=True, call=True)

    # -f = force (since the device may be in use)
    # -s = show progress
    # -v = verbose (print error count)
    # -w = destructive write+read test
    process = Spawn(['badblocks', '-fsvw', '-b', str(sector_size)] +
                    (['-e', str(self.args.max_errors)]
                     if self.args.max_errors else []) +
                    [self.device_path, str(last_block), str(first_block)],
                    log=True, bufsize=0,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    # The total number of phases there will be (8: read and write for each
    # of 4 different patterns).
    total_phases = 8

    # The phase we're currently in (0-relative).
    current_phase = 0

    # How far we are through the current phase.
    fraction_within_phase = 0

    buf = []
    lines = []

    self._UpdateSATALinkSpeed()
    self._LogSmartctl()

    def UpdatePhase():
      self._event_log.Log('start_phase', current_phase=current_phase)
      self.ui.SetHTML(MakeLabel('Phase', '阶段') + ' %d/%d: ' % (
          min(current_phase + 1, total_phases), total_phases),
                      id='bb-phase')
    UpdatePhase()

    while True:
      # Assume no output in timeout_secs means hung on disk op.
      start_time = time.time()
      rlist, _, _ = select([process.stdout], [], [], self.args.timeout_secs)
      end_time = time.time()
      self._UpdateSATALinkSpeed()

      if end_time - start_time > self.args.log_threshold_secs:
        factory.console.warn('Delay of %.2f s between badblocks progress lines',
                             end_time - start_time)
        self._event_log.Log('delay', duration_secs=end_time - start_time)

      self.assertTrue(
          rlist,
          'Timeout: No badblocks output for %.2f s' % self.args.timeout_secs)

      ch = process.stdout.read(1)
      if ch in ['', '\x08', '\r', '\n']:
        line = ''.join(buf).strip()
        if line:
          logging.info('badblocks> %s', line)

          match = re.search(r'([.0-9]+)% done, ', line)
          if match:
            # The percentage reported is actually the percentage until the last
            # block; convert it to an offset within the current phase.
            block_offset = (
                float(match.group(1)) / 100) * (last_block + 1)
            fraction_within_phase = (block_offset - first_block) / float(
                last_block + 1 - first_block)
            self.ui.SetHTML(line[match.end():], id='bb-progress')
            line = line[:match.start()].strip()  # Remove percentage from status

          line = line.rstrip(':')

          if line and line != 'done':
            self.ui.SetHTML(Escape(line), id='bb-status')

          # Calculate overall percentage done.
          fraction_done = (current_phase / float(total_phases) +
                           max(0, fraction_within_phase) / float(total_phases))
          self.template.SetProgressBarValue(round(fraction_done * 100))

          if line.startswith('done'):
            current_phase += 1
            UpdatePhase()
            fraction_within_phase = 0
          lines.append(line)

        if ch == '':
          break
        buf = []
      else:
        buf.append(ch)

    self.assertEquals(
        0, process.wait(),
        'badblocks returned with error code %d' % process.returncode)

    last_line = lines[-1]
    self.assertEquals('Pass completed, 0 bad blocks found. (0/0/0 errors)',
                      last_line)

  def _LogSmartctl(self):
    smartctl_output = Spawn(['smartctl', '-a', self.device_path],
                            check_output=True).stdout_data
    self._event_log.Log('smartctl', stdout=smartctl_output)
    logging.info('smartctl output: %s', smartctl_output)

    self.assertTrue(
        'SMART overall-health self-assessment test result: PASSED'
        in smartctl_output,
        'SMART says drive is not healthy')

  def _UpdateSATALinkSpeed(self):
    '''Updates the current SATA link speed based on /var/log/messages.'''
    first_time = self.sata_link_speed_mbps is None
    if not self.var_log_messages:
      self.var_log_messages = open('/var/log/messages')

    # List of dicts to log.
    events = []

    while True:
      log_line = self.var_log_messages.readline()
      if not log_line:
        break
      log_line = log_line.strip()
      match = re.match(r'(\S)+.+SATA link up ([0-9.]+) (G|M)bps', log_line)
      if match:
        self.sata_link_speed_mbps = (
            int(float(match.group(2)) *
                (1000 if match.group(3) == 'G' else 1)))
        events.append(dict(speed_mbps=self.sata_link_speed_mbps,
                           log_line=log_line))

    if first_time and events:
      # First time, ignore all but the last
      events = events[-1:]

    for event in events:
      logging.info('SATA link info: %r', event)
      self._event_log.Log('sata_link_info', **event)
