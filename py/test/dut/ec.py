#!/usr/bin/env python
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""System EC service provider.

This module provides accessing Embedded Controller (EC) on a device.
"""

from __future__ import print_function
import re

import factory_common  # pylint: disable=W0611
from cros.factory.test.dut import component


class EmbeddedController(component.DUTComponent):
  """System module for embedded controller."""

  # Regular expression for parsing ectool output.
  I2C_READ_RE = re.compile(r'I2C port \d+ at \S+ offset \S+ = (0x[0-9a-f]+)')

  # EC tool arguments for accessing PD. Subclass may override this to match the
  # arguments used on the actual board. For example, boards with separate PD
  # like samus=Pixel2015), this should be ['--interface=dev', '--dev=1'].
  ECTOOL_PD_ARGS = []

  # USB PD info.
  USB_PD_INFO_RE_ALL = {
      'USB_PD_INFO_RE_V0':
          re.compile(
              r'Port C(?P<port>\d+) is (?P<enabled>enabled|disabled), '
              r'Role:(?P<role>SRC|SNK) Polarity:(?P<polarity>CC1|CC2) '
              r'State:(?P<state>\d+)'),
      'USB_PD_INFO_RE_V1':
          re.compile(
              r'Port C(?P<port>\d+) is (?P<enabled>enabled|disabled), '
              r'Role:(?P<role>SRC|SNK) (?P<datarole>DFP|UFP) '
              r'Polarity:(?P<polarity>CC1|CC2) State:(?P<state>\w+)'),
      'USB_PD_INFO_RE_V1_1':
          re.compile(
              r'Port C(?P<port>\d+) is (?P<enabled>enabled|disabled),'
              r'(?P<connected>connected|disconnected), '
              r'Role:(?P<role>SRC|SNK) (?P<datarole>DFP|UFP) '
              r'Polarity:(?P<polarity>CC1|CC2) State:(?P<state>\w+)'),
      'USB_PD_INFO_RE_V1_2':
          re.compile(
              r'Port C(?P<port>\d+): (?P<enabled>enabled|disabled), '
              r'(?P<connected>connected|disconnected)  State:(?P<state>\w+)\n'
              r'Role:(?P<role>SRC|SNK) (?P<datarole>DFP|UFP) *(?P<vconn>VCONN|), '
              r'Polarity:(?P<polarity>CC1|CC2)'),
  }

  def GetECVersion(self):
    """Gets the EC firmware version.

    Returns:
      A string of the EC firmware version.
    """
    return self._dut.CallOutput(
        ['mosys', 'ec', 'info', '-s', 'fw_version']).strip()

  def GetPDVersion(self):
    """Gets the PD firmware version.

    Returns:
      A string of the PD firmware version.
    """
    return self._dut.CallOutput(
        ['mosys', 'pd', 'info', '-s', 'fw_version']).strip()

  def GetECConsoleLog(self):
    """Gets the EC console log.

    Returns:
      A string containing EC console log.
    """
    return self._dut.CallOutput(
        ['ectool', 'console']).strip()

  def GetECPanicInfo(self):
    """Gets the EC panic info.

    Returns:
      A string of EC panic info.
    """
    return self._dut.CallOutput(
        ['ectool', 'panicinfo']).strip()

  def ProbeEC(self):
    """Says hello to EC.
    """
    try:
      if self._dut.CallOutput(['ectool', 'hello']).find('EC says hello') == -1:
        raise self.Error('Did not find "EC says hello".')
    except Exception as e:
      raise self.Error('Unable to say hello: %s' % e)
    return True

  def I2CRead(self, port, addr, reg):
    """Reads 16-bit value from I2C bus connected via EC.

    This function cannot access system I2C buses that are not routed via EC.

    Args:
      port: I2C port ID.
      addr: I2C slave address.
      reg: Slave register address.

    Returns:
      Integer value read from slave.
    """
    try:
      ectool_output = self._dut.CheckOutput(
          ['ectool', 'i2cread', '16', str(port), str(addr), str(reg)])
      return int(self.I2C_READ_RE.findall(ectool_output)[0], 16)
    except Exception as e:  # pylint: disable=W0703
      raise self.Error('Unable to read from I2C: %s' % e)

  def I2CWrite(self, port, addr, reg, value):
    """Writes 16-bit value to I2C bus connected via EC.

    This function cannot access system I2C buses that are not routed via EC.

    Args:
      port: I2C port ID.
      addr: I2C slave address.
      reg: Slave register address.
      value: 16-bit value to write.
    """
    try:
      self._dut.CheckCall(['ectool', 'i2cwrite', '16', str(port), str(addr),
                           str(reg), str(value)])
    except Exception as e:  # pylint: disable=W0703
      raise self.Error('Unable to write to I2C: %s' % e)

  def GetPDGPIOValue(self, gpio_name):
    """Gets PD GPIO value.

    Args:
      gpio_name: GPIO name.

    Returns:
      Return 1 if GPIO is high; otherwise 0.

    """
    gpio_info_re = re.compile(r'^GPIO %s = (\d)' % gpio_name)
    response = self._dut.CheckOutput(
        ['ectool'] + self.ECTOOL_PD_ARGS + ['gpioget', gpio_name])
    gpio_value = gpio_info_re.findall(response)
    if gpio_value:
      return int(gpio_value[0])
    else:
      raise self.Error('Fail to get GPIO %s value' % gpio_name)


  def GetUSBPDStatus(self, port):
    """Gets the USB PD status.

    Args:
      port: The USB port number.

    Returns:
      A dict that contains the following fields:

        'enabled': True or False
        'role': 'SNK' or 'SRC'
        'polarity': 'CC1' or 'CC2'
        'state': <state>
    """
    response = self._dut.CheckOutput(
        ['ectool'] + self.ECTOOL_PD_ARGS + ['usbpd', '%d' % port])
    for pd_version, re_pattern in self.USB_PD_INFO_RE_ALL.iteritems():
      match = re_pattern.match(response)
      if match:
        status = dict(
            enabled=match.group('enabled') == 'enabled',
            role=match.group('role'),
            polarity=match.group('polarity'))
        if pd_version == 'USB_PD_INFO_RE_V0':
          status['state'] = int(match.group('state'))
        else:
          status['state'] = match.group('state')
          status['datarole'] = match.group('datarole')
          if (pd_version == 'USB_PD_INFO_RE_V1_1' or
              pd_version == 'USB_PD_INFO_RE_V1_2'):
            status['connected'] = match.group('connected') == 'connected'
            if pd_version == 'USB_PD_INFO_RE_V1_2':
              status['vconn'] = match.group('vconn')
        return status
    raise self.Error('Unable to parse USB PD status from: %s' % response)

