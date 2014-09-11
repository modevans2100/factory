# -*- coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''A factory test for basic WiFi and LTE connectivity.

The test accepts a list of wireless services, checks for their signal strength,
connects to them, and optionally tests data throughput rate using iperf.
'''

import dbus
import logging
import sys
import time
import unittest

from cros.factory.event_log import Log
from cros.factory.goofy.service_manager import GetServiceStatus
from cros.factory.goofy.service_manager import SetServiceStatus
from cros.factory.goofy.service_manager import Status
from cros.factory.test import factory
from cros.factory.test.args import Arg
from cros.factory.utils.net_utils import GetWLANInterface
from cros.factory.utils.net_utils import GetEthernetIp
from cros.factory.utils.process_utils import Spawn, SpawnOutput

try:
  sys.path.append('/usr/local/lib/flimflam/test')
  import flimflam  # pylint: disable=F0401
except:  # pylint: disable=W0702
  pass


_SERVICE_LIST = ['shill', 'shill_respawn', 'wpasupplicant', 'modemmanager']


def FlimGetService(flim, name):
  timeout = time.time() + 10
  while time.time() < timeout:
    service = flim.FindElementByPropertySubstring('Service', 'Name', name)
    if service:
      return service
    time.sleep(0.5)


def FlimGetServiceProperty(service, prop):
  timeout = time.time() + 10
  while time.time() < timeout:
    try:
      properties = service.GetProperties()
    except dbus.exceptions.DBusException as e:
      logging.exception('Error reading service property')
      time.sleep(1)
    else:
      return properties[prop]
  raise e

def FlimConfigureService(flim, name, password):
  wlan_dict = {
      'Type': 'wifi',
      'Mode': 'managed',
      'AutoConnect': False,
      'SSID': name}
  if password:
    wlan_dict['Security'] = 'psk'
    wlan_dict['Passphrase'] = password

  flim.manager.ConfigureService(wlan_dict)

class WirelessTest(unittest.TestCase):
  ARGS = [
    Arg('services', (list, tuple),
        'A list of WiFi or LTE services (name, password) tuple to test.'
        ' e.g. [("ssid1", "password1"), ("ssid2", "password2")].'
        ' Set password to None or "" if it is an open network.'
        'If services are not specified, this test will check for any AP.',
        optional=True),
    Arg('min_signal_quality', int,
        'Minimum signal strength required (range from 0 to 100).',
        optional=True),
    Arg('host', str,
        'Host running iperf in server mode, used for testing data '
        'transmission speed.',
        optional=True, default=None),
    Arg('transmit_time', int,
        'Time in seconds for which to transmit data.',
        optional=True, default=10),
    Arg('transmit_interval', (int, float),
        'There will be an overall average of transmission speed.  But it may '
        'also be useful to check bandwidth within subintervals of this time. '
        'This argument can be used to check bandwidth for every interval of n '
        'seconds.  There will be floor(transmit_time / n) intervals, and any '
        'remaining time < transmit_time will not be independently reported.',
        optional=True, default=1),
    Arg('throughput_threshold', int,
        'Required minimum throughput in bytes/sec.  If any intervals or the '
        'overall throughput is lower than this, we will fail.',
        optional=True, default=None),
  ]

  def _RunIperfClientAndParseThroughput(self):
    '''Invokes an iperf client and parses throughput.

    This function uses the following data members:
      self.args.host: the host running an iperf server.
      self.args.transmit_time: total time (seconds) to transmit data.
      self.args.transmit_interval: time (seconds) of each sub-interval.

    Returns:
      A dict containing:
        result: True if the function successfully connected to the iperf server,
            False otherwise.
        raw_output: raw CSV data output from iperf.
        throughput: a list of throughputs in bytes/second, where a[:-1] are for
            intervals and a[-1] is overall.
      raw_output and throughput are only valid if result is True.
    '''
    logging.info('Running iperf connecting to host %s for %d seconds',
        self.args.host, self.args.transmit_time)
    iperf_cmd = ['iperf',
        '--client', self.args.host,
        '--time', str(self.args.transmit_time),
        '--interval', str(self.args.transmit_interval),
        '--reportstyle', 'c']
    # We enclose the iperf call in timeout, since when given an unreachable
    # host, it seems to hang indefinitely.
    timeout_cmd = ['timeout',
        '--signal', 'KILL',
        # Add 5 seconds to allow for process overhead and connection time.
        str(self.args.transmit_time + 5)] + iperf_cmd
    iperf_output = SpawnOutput(timeout_cmd, log=True, ignore_stderr=True)

    # iperf outputs CSV with the following as its columns, with rows[:-1] for
    # intervals, and a[-1] for overall values:
    # 0: timestamp
    # 1: source_address
    # 2: source_port
    # 3: destination_address
    # 4: destination_port
    # 5: [unclear?]
    # 6: interval
    # 7: transferred_bytes
    # 8: bits_per_second
    # Check for properly-formatted output (CSV with 9 columns).  Also, ensure
    # that transferred_bytes > 0.  If these conditions fail, we can assume iperf
    # failed.
    iperf_output_table = \
        [x.split(',') for x in iperf_output.strip().split("\n")]
    if len(iperf_output_table[0]) != 9 or int(iperf_output_table[0][8]) <= 0:
      factory.console.info(
          'Failed to make a connection to %s, or received bogus '
          'output from iperf.', self.args.host)
      return {'result': False,
              'raw_output': iperf_output,
              'throughput': []}

    # We only need (bits_per_second / 8) as our return list of throughputs.
    throughputs = [int(x[8]) / 8.0 for x in iperf_output_table]
    factory.console.info(
        'Successfully connected to %s, transferred: %d bytes, '
        'time spent: %d sec, throughput: %d bytes/sec',
        self.args.host, int(iperf_output_table[-1][7]) / 8.0,
        self.args.transmit_time, throughputs[-1])
    return {'result': True,
            'raw_output': iperf_output,
            'throughput': throughputs}

  def setUp(self):
    for service in _SERVICE_LIST:
      if GetServiceStatus(service) == Status.STOP:
        SetServiceStatus(service, Status.START)
    dev = GetWLANInterface()
    if not dev:
      self.fail('No wireless interface')
    else:
      logging.info('ifconfig %s up', dev)
      Spawn(['ifconfig', dev, 'up'], check_call=True, log=True)

  def runTest(self):
    flim = flimflam.FlimFlam(dbus.SystemBus())

    if self.args.services is None:
      # Basic wifi test -- succeeds if it can see any AP
      found_ssids = set([])
      for service in flim.GetObjectList('Service'):
        service_type = FlimGetServiceProperty(service, 'Type')
        service_name = FlimGetServiceProperty(service, 'Name')
        if service_type != 'wifi':
          continue
        if service_name is None:
          continue
        found_ssids.add(service_name)
      if not found_ssids:
        self.fail("No SSIDs found.")
      logging.info('found SSIDs: %s', ', '.join(found_ssids))
    else:
      # Test Wifi signal strength for each service
      if not isinstance(self.args.services, list):
        self.args.services = [self.args.services]
      for name, password in self.args.services:
        service = FlimGetService(flim, name)
        if service is None:
          self.fail('Unable to find service %s' % name)

        if self.args.min_signal_quality is not None:
          strength = int(FlimGetServiceProperty(service, 'Strength'))
          factory.console.info('Service %s signal strength %d', name, strength)
          if strength < self.args.min_signal_quality:
            self.fail('Service %s signal strength %d < %d' %
                      (name, strength, self.args.min_signal_quality))

        if FlimGetServiceProperty(service, 'IsActive'):
          logging.warning('Already connected to %s', name)
        else:
          logging.info('Connecting to %s', name)
          FlimConfigureService(flim, name, password)
          success, diagnostics = flim.ConnectService(service=service)
          if not success:
            self.fail('Unable to connect to %s, diagnostics %s' % (name,
                                                                   diagnostics))
          else:
            factory.console.info('Successfully connected to service %s' % name)

        ethernet_ip = GetEthernetIp()
        if ethernet_ip:
          self.fail('Still got ethernet ip %r' % ethernet_ip)

        Spawn(['ifconfig'], check_call=True, log=True)

        # Try to test throughput with iperf if needed.
        if self.args.host is not None:
          ret = self._RunIperfClientAndParseThroughput()
          Log('throughput_test',
              result=ret['result'],
              raw_output=ret['raw_output'],
              throughput=ret['throughput'])

          if not ret['result']:
            self.fail(
                'Failed to make a connection to %s, or received bogus '
                'output from iperf.' % self.args.host)

          if self.args.throughput_threshold is not None:
            # We want to ensure that ALL measured throughputs are over the
            # threshold.  Filter throughputs for failed cases.
            failed_throughputs = [x for x in ret['throughput']
                if x < self.args.throughput_threshold]
            if failed_throughputs:
              self.fail(
                  'Throughputs: %s < %d bytes/sec didn\'t meet '
                  'the threshold requirement.' % (
                      str(["%d" % x for x in ret['throughput']]),
                      self.args.throughput_threshold))

        flim.DisconnectService(service)
