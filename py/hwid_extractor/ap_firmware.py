# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import glob
import importlib
import json
import logging
import os
import re
import subprocess
import time

from chromite.lib.firmware import ap_firmware_config

from cros.factory.utils import file_utils

FLASHROM_BIN = '/usr/sbin/flashrom'
FUTILITY_BIN = '/usr/bin/futility'
VPD_BIN = '/usr/sbin/vpd'
CMD_TIMEOUT_SECOND = 20

SERVO_TYPE_CCD = 'ccd_cr50'

CONFIG_FILE_PATTERN = os.path.join(
    os.path.dirname(ap_firmware_config.__file__), '[!_]*.py')
# This dict maps board names to the configuration object of each board.
BOARD = {}

HWID_RE = re.compile(r'^hardware_id: ([A-Z0-9- ]+)$')
SERIAL_NUMBER_RE = re.compile(r'^"serial_number"="([A-Za-z0-9]+)"$')

SUPPORTED_BOARDS_JSON = os.path.join(
    os.path.dirname(__file__), 'www', 'supported_boards.json')


def _InitializeBoardConfigurations():
  """Initialize configuration object of each board.

  All configurations of supported boards are under chromite
  `chromite.lib.firmware.ap_firmware_config`.

  The supported boards are dumped to supported-boards.json for the web UI.
  """
  for f in glob.glob(CONFIG_FILE_PATTERN):
    board = os.path.splitext(os.path.basename(f))[0]
    BOARD[board] = importlib.import_module(
        f'chromite.lib.firmware.ap_firmware_config.{board}')

  with open(SUPPORTED_BOARDS_JSON, 'w') as f:
    json.dump({'supportedBoards': sorted(BOARD)}, f)


_InitializeBoardConfigurations()


@contextlib.contextmanager
def _HandleDutControl(dut_on, dut_off, dut_control):
  """Execute dut_on before and dut_off after the context with dut_control."""
  try:
    dut_control.RunAll(dut_on)
    # Need to wait for SPI chip power to stabilize (for some designs)
    time.sleep(1)
    yield
  finally:
    dut_control.RunAll(dut_off)


def _GetHWID(firmware_binary_file):
  """Get HWID from ap firmware binary."""
  futility_cmd = [FUTILITY_BIN, 'gbb', firmware_binary_file]
  output = subprocess.check_output(futility_cmd, encoding='utf-8',
                                   timeout=CMD_TIMEOUT_SECOND)
  logging.debug('futility output:\n%s', output)
  output.split(':')
  m = HWID_RE.match(output.strip())
  return m and m.group(1)


def _GetSerialNumber(firmware_binary_file):
  """Get serial number from ap firmware binary."""
  vpd_cmd = [VPD_BIN, '-l', '-f', firmware_binary_file]
  output = subprocess.check_output(vpd_cmd, encoding='utf-8',
                                   timeout=CMD_TIMEOUT_SECOND)
  logging.debug('vpd output:\n%s', output)
  for line in output.splitlines():
    m = SERIAL_NUMBER_RE.match(line.strip())
    if m:
      return m.group(1)
  return None


def _CheckServoTypeIsCCD(dut_control):
  servo_type = dut_control.GetValue('servo_type')
  if servo_type != SERVO_TYPE_CCD:
    raise RuntimeError(f'Servo type is not ccd, got: {servo_type}')


class _ServoStatus:
  """Mock object for ap_firmware_config.

  We only support ccd.

  TODO(chungsheng): b/180554195, remove this workaround after splitting
  chromite.
  """
  is_ccd = True
  is_c2d2 = False
  is_micro = False
  is_v2 = False
  is_v4 = False

  def __init__(self, dut_control):
    self.serial = dut_control.GetValue('serialname')


def ExtractHWIDAndSerialNumber(board, dut_control):
  """Extract HWID and serial no. from DUT.

  Read the ap firmware binary from DUT and extract the info from it. Only the
  necessary blocks are read to reduce the reading time. Some dut-control
  commands are executed before and after `flashrom` to control the DUT status.

  Args:
    board: The name of the reference board of DUT which is extracted.
    dut_control: DUTControl interface object for dut-control commands.

  Returns:
    hwid, serial_number. The value may be None.
  """
  _CheckServoTypeIsCCD(dut_control)
  servo_status = _ServoStatus(dut_control)

  if board not in BOARD:
    raise ValueError(f'Board "{board}" is not supported.')
  ap_config = BOARD[board].get_config(servo_status)

  with file_utils.UnopenedTemporaryFile() as tmp_file, _HandleDutControl(
      ap_config.dut_control_on, ap_config.dut_control_off, dut_control):
    flashrom_cmd = [
        FLASHROM_BIN, '-i', 'FMAP', '-i', 'RO_VPD', '-i', 'GBB', '-p',
        ap_config.programmer, '-r', tmp_file
    ]
    output = subprocess.check_output(flashrom_cmd, encoding='utf-8',
                                     timeout=CMD_TIMEOUT_SECOND)
    logging.debug('flashrom output:\n%s', output)
    hwid = _GetHWID(tmp_file)
    serial_number = _GetSerialNumber(tmp_file)
    logging.info('Extract result: HWID: "%s", serial number: "%s"', hwid,
                 serial_number)

  return hwid, serial_number
