# -*- mode: python; coding: utf-8 -*-
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""WiFi: DUT API system module to control WiFi device.

WiFi is a DUT API system module to list and connect to WiFi networks.

Three different modules are provided:
- WiFi: Generic WiFi usage.
- WiFiChromeOS: Disables necessary services, and uses dhclient.
- WiFiAndroid: Uses dhcpcd.

The WiFi class can also be subclassed for any future devices with different
requirements.

Example usage::

  ap = dut.wifi.FindAccessPoint(ssid='GoogleGuest')
  print(u'SSID: %s, strength: %.2f dBm' % (ap.ssid, ap.strength))
  conn = dut.wifi.Connect(ap, passkey='my_pass_key')
  conn.Disconnect()
"""


from __future__ import print_function

import logging
import os
import re
import textwrap

import factory_common  # pylint: disable=W0611
from cros.factory.test.dut import component
from cros.factory.test.dut.component import CalledProcessError
from cros.factory.test.env import paths
from cros.factory.utils import sync_utils


class WiFiError(Exception):
  """Error with some WiFi-related functionality."""
  pass


class WiFi(component.DUTComponent):
  """WiFi system component."""
  _SCAN_TIMEOUT_SECS = 10
  _ACCESS_POINT_RE = re.compile(r'BSS ([:\w]*)\(on \w*\)( -- associated)?\r?\n')
  _WLAN_NAME_PATTERNS = ['wlan*', 'mlan*']

  # Shortcut to access exception object.
  WiFiError = WiFiError

  def __init__(self, dut, tmp_dir=None):
    super(WiFi, self).__init__(dut)
    self.tmp_dir = tmp_dir

  def _NewConnection(self, *args, **kwargs):
    """Create a new Connection object with the given arguments.

    Can be overridden in a subclass to send custom arguments to the Connection
    class.
    """
    return Connection(*args, dhcp_method=Connection.DHCP_DHCPCD, **kwargs)

  def GetInterfaces(self, name_patterns=None):
    """Return the interfaces for wireless LAN devices.

    Args:
      name_patterns: A list that contains all name patterns of WiFi interfaces.

    Returns:
      A list like ['wlan0', 'mlan0'] if those wireless LAN interfaces are
      available.  Returns [] if there are no wireless LAN interfaces.
    """
    if not name_patterns:
      name_patterns = self._WLAN_NAME_PATTERNS
    interfaces = []
    for pattern in name_patterns:
      interfaces += [self._dut.path.basename(path) for path in
                     self._dut.Glob('/sys/class/net/' + pattern) or []]
    return interfaces

  def _ValidateInterface(self, interface=None):
    """Return either provided interface, or one retrieved from system."""
    if interface:
      return interface

    interfaces = self.GetInterfaces()
    if not interfaces:
      raise WiFiError('No available WLAN interfaces.')

    # Arbitrarily choose first interface.
    return interfaces[0]

  def _AllAccessPoints(self, interface=None, scan_timeout=None):
    """Retrieve a list of AccessPoint objects."""
    if scan_timeout is None:
      scan_timeout = self._SCAN_TIMEOUT_SECS

    # First, bring the device up.  If it is already up, this will succeed
    # anyways.
    logging.debug('Bringing up ifconfig...')
    self._dut.CheckCall(['ifconfig', interface, 'up'])

    # Grab output from the iw 'scan' command on the requested interface.  This
    # sometimes fails if the device is busy, so we may need to retry it a few
    # times before getting output.
    def TryScan():
      try:
        return self._dut.CheckOutput(['iw', 'dev', interface, 'scan'])
      except CalledProcessError:
        return False
    output = sync_utils.PollForCondition(
        poll_method=TryScan,
        timeout_secs=scan_timeout,
        poll_interval_secs=0,
        condition_name='Attempting iw scan...').decode('string_escape')

    if not output:
      raise WiFiError('Unable to scan device for access points')

    return self._ParseScanResult(output)

  def _ParseScanResult(self, output):
    """Parse output from iw scan into AccessPoint objects."""
    # Split access points into a list.  Since we split on a string encountered
    # at the very beginning of the output, the first element is blank (thus
    # we skip the first element).  Remaining elements are in groups of three,
    # in groups of: (BSSID, associated, other).
    bssid_ap_list = self._ACCESS_POINT_RE.split(output)[1:]
    bssid_ap_tuples = [bssid_ap_list[x:x+3]
                       for x in xrange(0, len(bssid_ap_list), 3)]

    # Parse each AP.
    aps = []
    for bssid, associated, ap_data in bssid_ap_tuples:
      active = bool(associated)
      aps.append(self._ParseScanAccessPoint(bssid, active, ap_data))

    # Return AP list.
    return aps

  def _ParseScanAccessPoint(self, bssid, active, output):
    """Parse a particular AP in iw scan output into an AccessPoint object.

    Some of the logic in this function was derived from information here:
    https://wiki.archlinux.org/index.php/Wireless_network_configuration

    Args:
      bssid: BSSID of the access point in question.
      active: None if not associated to this AP.
      output: Output section from iw scan command for this particular AP.
        Should not include the first line showing the BSSID.

    Returns:
      An AccessPoint object representing the parsed access point.
    """
    logging.debug('BSSID %s data: %s', bssid, output)
    ap = AccessPoint()
    ap.bssid = bssid
    ap.active = active
    encrypted = None

    for line in textwrap.dedent(output).splitlines():
      if ':' in line:
        key, _, value = [x.strip() for x in line.partition(':')]

        if key == 'SSID':
          ap.ssid = value.decode('utf-8')

        elif key == 'signal':
          ap.strength = float(value.partition(' dBm')[0])

        elif key == 'capability':
          encrypted = 'Privacy' in value

        elif key == 'WPA':
          ap.encryption_type = 'wpa'

        elif key == 'RSN':
          ap.encryption_type = 'wpa2'

        elif key == 'freq':
          ap.frequency = int(value)

        # The primary channel is located within the "HT operation" section.
        elif key.strip() == '* primary channel':
          ap.channel = int(value)

    # If no encryption type was encountered, but encryption is in place, the AP
    # uses WEP encryption.
    if encrypted and not ap.encryption_type:
      ap.encryption_type = 'wep'

    return ap

  def FindAccessPoint(
      self, ssid=None, active=None, encrypted=None, interface=None,
      scan_timeout=_SCAN_TIMEOUT_SECS):
    """Retrieve the first AccessPoint object with the given criteria."""
    interface = self._ValidateInterface(interface)
    matches = self.FilterAccessPoints(
        interface=interface,
        ssid=ssid,
        active=active,
        encrypted=encrypted,
        scan_timeout=scan_timeout)
    if not matches:
      raise WiFiError('No matching access points found')
    return matches[0] if matches else None

  def FilterAccessPoints(
      self, ssid=None, active=None, encrypted=None, interface=None,
      scan_timeout=None):
    """Retrieve a list of AccessPoint objects matching criteria."""
    interface = self._ValidateInterface(interface)
    return [ap for ap in self._AllAccessPoints(interface=interface,
                                               scan_timeout=scan_timeout)
            if ((ssid is None or ssid == ap.ssid) and
                (active is None or active == ap.active) and
                (encrypted is None or encrypted == ap.encrypted))]

  def Connect(self, ap, interface=None, passkey=None,
              connect_timeout=None, dhcp_timeout=None):
    """Connect to a given AccessPoint.

    Returns:
      A connected Connection object.
    """
    if not isinstance(ap, AccessPoint):
      raise WiFiError('Expected AccessPoint for ap argument')
    interface = self._ValidateInterface(interface)
    conn = self._NewConnection(
        dut=self._dut, interface=interface,
        ap=ap, passkey=passkey,
        connect_timeout=connect_timeout, dhcp_timeout=dhcp_timeout,
        tmp_dir=self.tmp_dir)
    conn.Connect()
    return conn

  def FindAndConnectToAccessPoint(
          self, ssid=None, interface=None, passkey=None, scan_timeout=None,
          connect_timeout=None, dhcp_timeout=None, **kwargs):
    """Try to find the given AccessPoint and connect to it.

    Returns:
      A connected Connection object.
    """
    interface = self._ValidateInterface(interface)
    ap = self.FindAccessPoint(ssid=ssid, interface=interface,
                              scan_timeout=scan_timeout, **kwargs)
    if not ap:
      raise WiFiError('Could not find AP with ssid=%s' % ssid)
    return self.Connect(ap, interface=interface, passkey=passkey,
                        connect_timeout=connect_timeout,
                        dhcp_timeout=dhcp_timeout)


class AccessPoint(object):
  """Represents a WiFi access point.

  Properties:
    ssid: SSID of AP (decoded into UTF-8 string).
    bssid: BSSID of AP (string with format 'xx:xx:xx:xx:xx:xx').
    channel: Channel of the AP (integer).
    frequency: Frequency of the AP (MHz as integer).
    active: Whether or not this network is currently associated.
    strength: Signal strength in dBm.
    encryption_type: Type of encryption used.  Can be one of:
      None, 'wep', 'wpa', 'wpa2'.
  """

  def __init__(self):
    self.ssid = None
    self.bssid = None
    self.channel = None
    self.frequency = None
    self.active = None
    self.strength = None
    self.encryption_type = None

  @property
  def encrypted(self):
    """Whether or not this AP is encrypted.

    False implies encryption_type == None.
    """
    return self.encryption_type is not None

  def __repr__(self):
    if not self.bssid:
      return 'AccessPoint()'
    return (
        u'AccessPoint({ssid}, {bssid}, channel={channel}, '
        'frequency={frequency} MHz, {active}, '
        '{strength:.2f} dBm, encryption={encryption})'.format(
            ssid=self.ssid,
            bssid=self.bssid,
            channel=self.channel,
            frequency=self.frequency,
            active='active' if self.active else 'inactive',
            strength=self.strength,
            encryption=self.encryption_type or 'none')).encode('utf-8')


class WiFiAndroid(WiFi):
  """WiFi system module for Android systems."""
  def _NewConnection(self, *args, **kwargs):
    """See WiFi._NewConnection for details.

    Customizes DHCP method for Android devices.
    """
    kwargs.setdefault('dhcp_method', Connection.DHCP_DHCPCD)

    return Connection(*args, **kwargs)


class WiFiChromeOS(WiFi):
  """WiFi system module for Chrome OS systems."""

  _DHCLIENT_SCRIPT_PATH = '/usr/local/sbin/dhclient-script'

  def _NewConnection(self, *args, **kwargs):
    """Create a new Connection object with the given arguments.

    Selects dhclient DHCP method for Chrome OS devices.
    Disables wpasupplicant when making a connection to an AP.
    """
    kwargs.setdefault('dhcp_method', Connection.DHCP_DHCLIENT)
    kwargs.setdefault('dhclient_script_path', self._DHCLIENT_SCRIPT_PATH)

    # Disables the wpasupplicant service, which seems to interfere with
    # the device during connection.  We make the assumption that wpasupplicant
    # will not be used by other parts of the factory test flow.
    # We add a sleep because it seems that if we continue bringing up the
    # WLAN interface directly afterwards, it has a change of being brought
    # right back down (either by wpasupplicant or something else).
    # TODO(kitching): Figure out a better way of either (a) disabling these
    # services temporarily, or (b) using Chrome OS's Shill to make the
    # connection.
    self._dut.Call('stop wpasupplicant && sleep 0.5')
    return Connection(*args, **kwargs)


class Connection(object):
  """Represents a connection to a particular AccessPoint."""
  DHCP_DHCPCD = 'dhcpcd'
  DHCP_DHCLIENT = 'dhclient'
  _CONNECT_TIMEOUT = 10
  _DHCP_TIMEOUT = 10

  def __init__(self, dut, interface, ap, passkey,
               connect_timeout=None, dhcp_timeout=None,
               tmp_dir=None, dhcp_method=DHCP_DHCLIENT,
               dhclient_script_path=None):
    self._dut = dut
    self.interface = interface
    self.ap = ap
    self.passkey = passkey

    # IP can be queried after connecting.
    self.ip = None

    self._auth_process = None
    self._dhcp_process = None
    self._connect_timeout = (self._CONNECT_TIMEOUT if connect_timeout is None
                            else connect_timeout)
    self._dhcp_timeout = (self._DHCP_TIMEOUT if dhcp_timeout is None
                         else dhcp_timeout)
    self._user_tmp_dir = tmp_dir
    if dhcp_method == self.DHCP_DHCPCD:
      self._dhcp_fn = self._RunDHCPCD
    else:
      self._dhcp_fn = self._RunDHCPClient

    # Arguments for DHCP function.
    self._dhcp_args = {'dhclient_script_path': dhclient_script_path}

  def _DisconnectAP(self):
    """Disconnect from the current AP."""
    disconnect_command = 'iw dev {interface} disconnect'.format(
        interface=self.interface)
    # This call may fail if we are not connected to any network.
    self._dut.Call(disconnect_command)

  def _WaitConnectAP(self):
    """Block until authenticated and connected to the AP."""
    CHECK_SUCCESS_PREFIX = 'Connected to'
    check_command = 'iw dev {interface} link'.format(interface=self.interface)
    logging.info('Waiting to connect to AP...')
    def Connected():
      return self._dut.CheckOutput(
          check_command).startswith(CHECK_SUCCESS_PREFIX)
    return sync_utils.WaitFor(Connected, self._connect_timeout)

  def Connect(self):
    """Connect to the AP."""
    if self.ap.encrypted and not self.passkey:
      raise WiFiError('Require passkey to connect to encrypted network')
    self._DisconnectAP()

    # Create temporary directory.
    if self._user_tmp_dir:
      self._tmp_dir = self._user_tmp_dir
    else:
      self._tmp_dir_handle = self._dut.temp.TempDirectory()
      self._tmp_dir = self._tmp_dir_handle.__enter__()

    # First, bring the device up.  If it is already up, this will succeed
    # anyways.
    logging.debug('Bringing up ifconfig...')
    self._dut.CheckCall(['ifconfig', self.interface, 'up'])

    # Authenticate to the server.
    auth_fns = {
        'wep': self._AuthenticateWEP,
        'wpa': self._AuthenticateWPA,
        'wpa2': self._AuthenticateWPA}
    auth_process = auth_fns.get(
        self.ap.encryption_type, self._AuthenticateOpen)()
    auth_process.next()

    # Grab an IP address.
    dhcp_process = self._dhcp_fn(**self._dhcp_args)
    self.ip = dhcp_process.next()

    # Store for disconnection.
    self._auth_process = auth_process
    self._dhcp_process = dhcp_process

  def Disconnect(self):
    """Disconnect from the AP."""
    if not self._auth_process or not self._dhcp_process:
      raise WiFiError('Must connect before disconnecting')

    self.ip = None
    dhcp_process, self._dhcp_process = self._dhcp_process, None
    auth_process, self._auth_process = self._auth_process, None
    dhcp_process.next()
    auth_process.next()

    # Remove temporary directory.
    if not self._user_tmp_dir:
      self._tmp_dir_handle.__exit__(None, None, None)
      self._tmp_dir = None

  def _LeasedIP(self):
    """Return current leased IP.

    Returns:
      Leased IP as a string or False if not yet leased.
    """
    check_command = 'ip addr show {interface} | grep "inet "'.format(
        interface=self.interface)
    try:
      # grep exit with return code 0 when we have retrieved an IP.
      out = self._dut.CheckOutput(check_command)
    except CalledProcessError:
      return False
    # ex: inet 192.168.159.78/20 brd 192.168.159.255 scope global wlan0
    return out.split()[1].split('/')[0]

  def _RunDHCPCD(self, **kwargs):
    """Grab an IP for the device using the dhcpcd command."""
    del kwargs
    clear_ifconfig_command = 'ifconfig {interface} 0.0.0.0'.format(
        interface=self.interface)
    dhcp_command = ('dhcpcd -t {timeout} {interface}').format(
        timeout=self._dhcp_timeout,
        interface=self.interface)
    dhcp_timeout_command = 'timeout {timeout} {cmd}'.format(
        timeout=self._dhcp_timeout,
        cmd=dhcp_command)
    force_kill_command = 'pgrep dhcpcd | xargs -r kill -9'

    logging.info('Killing any existing dhcpcd processes...')
    self._dut.Call(force_kill_command)

    logging.info('Clearing any existing ifconfig networks...')
    self._dut.Call(clear_ifconfig_command)

    logging.info('Starting dhcpcd...')
    self._dut.CheckCall(dhcp_timeout_command)

    logging.info('Verifying IP address...')
    ip = self._LeasedIP()
    if not ip:
      self._dut.Call(force_kill_command)
      raise WiFiError('DHCP bind failed')
    logging.info('Success: bound to IP %s', ip)

    yield ip  # We have bound an IP; yield back to the caller.

    logging.info('Killing any remaining dhcpcd processes...')
    self._dut.Call(force_kill_command)

    yield  # We have released the IP.

  def _RunDHCPClient(self, dhclient_script_path=None, **kwargs):
    """Grab an IP for the device using the dhclient command."""
    del kwargs
    PID_FILE = os.path.join(self._tmp_dir, 'dhclient.pid')
    clear_ifconfig_command = 'ifconfig {interface} 0.0.0.0'.format(
        interface=self.interface)
    dhcp_command = ('echo "" | '  # dhclient expects STDIN for some reason
                    'dhclient -4 '  # only run on IPv4
                    '-nw '  # immediately daemonize
                    '-pf {pid_file} '
                    '-sf {dhclient_script} '
                    '-lf /dev/null '  # don't keep a leases file
                    '-v {interface}'.format(
                        pid_file=PID_FILE,
                        dhclient_script=dhclient_script_path,
                        interface=self.interface))
    kill_command = 'cat {pid_file} | xargs -r kill; rm {pid_file}'.format(
        pid_file=PID_FILE)
    force_kill_command = 'pgrep dhclient | xargs -r kill -9'

    logging.info('Killing any existing dhclient processes...')
    self._dut.Call(force_kill_command)

    logging.info('Clearing any existing ifconfig networks...')
    self._dut.Call(clear_ifconfig_command)

    logging.info('Starting dhclient...')
    self._dut.CheckCall(dhcp_command)

    logging.info('Waiting to lease an IP...')
    ip = sync_utils.WaitFor(self._LeasedIP, self._dhcp_timeout)
    if not ip:
      self._dut.Call(kill_command)
      raise WiFiError('DHCP bind failed')
    logging.info('Success: bound to IP %s', ip)

    yield ip  # We have bound an IP; yield back to the caller.

    logging.info('Stopping dhclient...')
    self._dut.Call(kill_command)
    self._dut.Call(force_kill_command)

    yield  # We have released the IP.

  def _AuthenticateOpen(self):
    """Connect to an open network."""
    # TODO(kitching): Escape quotes in ssid properly.
    connect_command = u'iw dev {interface} connect {ssid}'.format(
        interface=self.interface,
        ssid=self.ap.ssid)

    logging.info('Connecting to open network...')
    self._dut.CheckCall(connect_command)

    # Pause until connected.  Throws exception if failed.
    if not self._WaitConnectAP():
      raise WiFiError('Connection to open network failed')

    yield  # We are connected; yield back to the caller.

    logging.info('Disconnecting from open network...')
    self._DisconnectAP()

    yield  # We have disconnected.

  def _AuthenticateWEP(self):
    """Authenticate and connect to a WEP network."""
    # TODO(kitching): Escape quotes in ssid and passkey properly.
    connect_command = (
        u'iw dev {interface} connect {ssid} key 0:{passkey}'.format(
            interface=self.interface,
            ssid=self.ap.ssid,
            passkey=self.passkey))

    logging.info('Authenticating to WEP network...')
    self._dut.CheckCall(connect_command)

    # Pause until connected.  Throws exception if failed.
    if not self._WaitConnectAP():
      raise WiFiError('Connection to WEP network failed')

    yield  # We are connected; yield back to the caller.

    logging.info('Disconnecting from WEP network...')
    self._DisconnectAP()

    yield  # We have disconnected.

  def _AuthenticateWPA(self):
    """Authenticate and connect to a WPA network."""
    if self.passkey is None:
      raise WiFiError('Passkey is needed for WPA/WPA2 authentication')

    PID_FILE = os.path.join(self._tmp_dir, 'wpa_supplicant.pid')
    WPA_FILE = os.path.join(self._tmp_dir, 'wpa.conf')
    # TODO(kitching): Escape quotes in ssid and passkey properly.
    wpa_passphrase_command = (
        u'wpa_passphrase {ssid} {passkey} > {wpa_file}'.format(
            ssid=self.ap.ssid,
            passkey=self.passkey,
            wpa_file=WPA_FILE))
    wpa_supplicant_command = (
        'wpa_supplicant '
        '-B '  # daemonize
        '-P {pid_file} '
        '-D nl80211 '
        '-i {interface} '
        '-c {wpa_file}'.format(
            pid_file=PID_FILE,
            interface=self.interface,
            wpa_file=WPA_FILE))
    kill_command = (
        'cat {pid_file} | xargs -r kill; '
        'rm {pid_file}; rm {wpa_file}'.format(
            pid_file=PID_FILE,
            wpa_file=WPA_FILE))
    force_kill_command = 'killall wpa_supplicant'

    logging.info('Killing any existing wpa_command processes...')
    self._dut.Call(force_kill_command)

    logging.info('Creating wpa.conf...')
    self._dut.CheckCall(wpa_passphrase_command)

    logging.info('Launching wpa_supplicant...')
    self._dut.CheckCall(wpa_supplicant_command)

    # Pause until connected.  Throws exception if failed.
    if not self._WaitConnectAP():
      self._dut.Call(kill_command)
      raise WiFiError('Connection to WPA network failed')

    yield  # We are connected; yield back to the caller.

    logging.info('Stopping wpa_supplicant...')
    self._dut.Call(kill_command)
    self._dut.Call(force_kill_command)

    logging.info('Disconnecting from WPA network...')
    self._DisconnectAP()

    yield  # We have disconnected.