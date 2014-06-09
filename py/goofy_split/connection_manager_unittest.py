#!/usr/bin/python -u
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import dbus
import glob
import mox
import os
import subprocess
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.goofy import connection_manager


_FAKE_MANAGER = 'flimflam'
_FAKE_PROC_NAME = 'shill'
_FAKE_SCAN_INTERVAL_SECS = 10
_FAKE_SUBSERVICE_LIST = ['flimflam_respawn', 'wpasupplicant', 'modemmanager']
_FAKE_PROFILE_LOCATION = '/var/cache/%s/default.profile'
_FAKE_INTERFACES = ['wlan0', 'eth0', 'lo']
_FAKE_DATA = {
  'scan_interval': _FAKE_SCAN_INTERVAL_SECS,
  'network_manager': _FAKE_MANAGER,
  'process_name': _FAKE_PROC_NAME,
  'subservices': _FAKE_SUBSERVICE_LIST,
  'profile_path': _FAKE_PROFILE_LOCATION
  }


class WLANTest(unittest.TestCase):
  def setUp(self):
    self.mox = mox.Mox()

  def tearDown(self):
    self.mox.VerifyAll()
    self.mox.UnsetStubs()

  def testWLANFailWPASecurity(self):
    self.mox.ReplayAll()
    self.assertRaises(connection_manager.ConnectionManagerException,
                      connection_manager.WLAN,
                      ssid='fake_server1', security='wpa', passphrase='1')

  def testWLANFailInvalidSecurity(self):
    self.mox.ReplayAll()
    self.assertRaises(connection_manager.ConnectionManagerException,
                      connection_manager.WLAN,
                      ssid='fake_server1', security='ABC', passphrase='1')


class ConnectionManagerTest(unittest.TestCase):
  def setUp(self):
    self.mox = mox.Mox()
    self.mox.StubOutWithMock(connection_manager, 'GetBaseNetworkManager')
    self.mox.StubOutWithMock(glob, 'glob')
    self.mox.StubOutWithMock(subprocess, 'call')
    self.fakeBaseNetworkManager = self.mox.CreateMockAnything()
    self.fakeData = _FAKE_DATA.copy()
    self.fakeData['wlans'] = [connection_manager.WLAN(ssid='fake_server',
                                                      security='psk',
                                                      passphrase='test0000')]

  def tearDown(self):
    self.mox.VerifyAll()
    self.mox.UnsetStubs()

  def MockDisableNetworking(self):
    for service in _FAKE_SUBSERVICE_LIST + [_FAKE_MANAGER]:
      subprocess.call("stop %s" % service, shell=True,
                      stdout=mox.IgnoreArg(), stderr=mox.IgnoreArg())
    interfaces = list(_FAKE_INTERFACES)
    interfaces.remove('lo')
    glob.glob('/sys/class/net/*').AndReturn(_FAKE_INTERFACES)
    for dev in interfaces:
      subprocess.call("ifconfig %s down" % dev, shell=True,
                      stdout=mox.IgnoreArg(), stderr=mox.IgnoreArg())

  def MockEnableNetworking(self, reset=True):
    if reset:
      self.MockDisableNetworking()
      self.mox.StubOutWithMock(os, 'remove')
      os.remove(_FAKE_PROFILE_LOCATION % _FAKE_PROC_NAME)

    interfaces = list(_FAKE_INTERFACES)
    interfaces.remove('lo')
    glob.glob('/sys/class/net/*').AndReturn(_FAKE_INTERFACES)
    for dev in interfaces:
      subprocess.call("ifconfig %s up" % dev, shell=True,
                      stdout=mox.IgnoreArg(), stderr=mox.IgnoreArg())

    for service in [_FAKE_MANAGER] + _FAKE_SUBSERVICE_LIST:
      subprocess.call("start %s" % service, shell=True,
                      stdout=mox.IgnoreArg(), stderr=mox.IgnoreArg())

    connection_manager.GetBaseNetworkManager().AndReturn(
      self.fakeBaseNetworkManager)
    glob.glob('/sys/class/net/*').AndReturn(_FAKE_INTERFACES)
    fakeDevice = self.mox.CreateMockAnything()
    self.fakeBaseNetworkManager.FindElementByNameSubstring(
      'Device', 'wlan0').AndReturn(fakeDevice)
    fakeDevice.SetProperty('ScanInterval',
                           dbus.UInt16(_FAKE_SCAN_INTERVAL_SECS))

    fakeMgr = self.mox.CreateMockAnything()
    self.fakeBaseNetworkManager.manager = fakeMgr
    self.fakeBaseNetworkManager.manager.ConfigureService({
      'Type': 'wifi',
      'Mode': 'managed',
      'AutoConnect': True,
      'SSID': 'fake_server',
      'Security': 'psk',
      'Passphrase': 'test0000'
      })

  def testInitWithEnableNetworking(self):
    self.MockEnableNetworking(reset=False)

    self.mox.ReplayAll()
    connection_manager.ConnectionManager(start_enabled=True,
                                         **self.fakeData)

  def testInitWithDisableNetworking(self):
    self.MockDisableNetworking()

    self.mox.ReplayAll()
    connection_manager.ConnectionManager(start_enabled=False,
                                         **self.fakeData)

  def testInitFailInvalidNetworkManager(self):
    self.mox.ReplayAll()
    self.assertRaises(AssertionError, connection_manager.ConnectionManager,
                      network_manager='ABC')

  def testInitFailInvalidProcessName(self):
    self.mox.ReplayAll()
    self.assertRaises(AssertionError, connection_manager.ConnectionManager,
                      process_name='XYZ')

  def testIsConnectedOK(self):
    self.MockDisableNetworking()
    connection_manager.GetBaseNetworkManager().AndReturn(
      self.fakeBaseNetworkManager)
    self.fakeBaseNetworkManager.GetSystemState().AndReturn('online')

    self.mox.ReplayAll()
    x = connection_manager.ConnectionManager(start_enabled=False,
                                             **self.fakeData)
    self.assertEqual(x.IsConnected(), True)

  def testIsConnectedFailNotConnected(self):
    self.MockDisableNetworking()
    connection_manager.GetBaseNetworkManager().AndReturn(
      self.fakeBaseNetworkManager)
    self.fakeBaseNetworkManager.GetSystemState().AndReturn('offline')

    self.mox.ReplayAll()
    x = connection_manager.ConnectionManager(start_enabled=False,
                                             **self.fakeData)
    self.assertEqual(x.IsConnected(), False)

  def testIsConnectedFailNetworkManagerNotRunning(self):
    self.MockDisableNetworking()
    connection_manager.GetBaseNetworkManager().AndRaise(
            dbus.exceptions.DBusException("YAYA"))

    self.mox.ReplayAll()
    x = connection_manager.ConnectionManager(start_enabled=False,
                                             **self.fakeData)
    self.assertEqual(x.IsConnected(), False)


if __name__ == '__main__':
  unittest.main()
