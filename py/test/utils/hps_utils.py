# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""HPS utilities"""

import re
from typing import Optional, Tuple

from cros.factory.utils import process_utils
from cros.factory.utils import sys_interface


DEFAULT_HPS_FACTORY_PATH = 'hps-factory'
IOTOOLS_PATH = 'iotools'
MCU_ID_RE = re.compile(r'^MCU ID:\s*(\S+)\s*$', re.MULTILINE)
CAMERA_ID_RE = re.compile(r'^Camera ID:\s*(\S+)\s*$', re.MULTILINE)
SPI_FLASH_RE = re.compile(r'^SPI flash:\s*(\S+)\s*$', re.MULTILINE)


class HPSError(Exception):
  """HPS device exception class."""


class HPSDevice:

  def __init__(self, dut: sys_interface.SystemInterface,
               hps_factory_path: Optional[str] = None,
               dev: Optional[str] = None):
    self._dut = dut
    self._hps_factory_path = hps_factory_path or DEFAULT_HPS_FACTORY_PATH
    self._dev = dev

  def RunFactoryProcess(self, timeout_secs):
    cmd = [self._hps_factory_path, '--verbose']
    if self._dev is not None:
      cmd.extend(['--dev', self._dev])
    cmd.append('factory')
    # TODO(cyueh) Add timeout to sys_interface.SystemInterface.Popen
    process_utils.Spawn(cmd, timeout=timeout_secs, log=True, check_call=True)

  def PowerCycle(self):
    """Should be equivalent to the below command.

    iotools mmio_write32 0xfd6a0ae0 \
      $(iotools btr $(iotools mmio_read32 0xfd6a0ae0) 0) && \
    iotools mmio_write32 0xfd6a0ae0 \
      $(iotools bts $(iotools mmio_read32 0xfd6a0ae0) 0)
    """
    index = '0xfd6a0ae0'

    output = self._dut.CheckOutput([IOTOOLS_PATH, 'mmio_read32', index],
                                   log=True).strip()
    output = self._dut.CheckOutput([IOTOOLS_PATH, 'btr', output, '0'],
                                   log=True).strip()
    returncode = self._dut.Call([IOTOOLS_PATH, 'mmio_write32', index, output],
                                log=True)

    if returncode == 0:
      output = self._dut.CheckOutput([IOTOOLS_PATH, 'mmio_read32', index],
                                     log=True).strip()
      output = self._dut.CheckOutput([IOTOOLS_PATH, 'bts', output, '0'],
                                     log=True).strip()
      self._dut.Call([IOTOOLS_PATH, 'mmio_write32', index, output], log=True)

  def GetHPSInfo(self) -> Tuple[str, str, str]:
    """Retrieves the HPS identifiers.

    Returns:
      An tuple (MCU_ID, CAMERA_ID, SPI_FLASH_ID) of three strings.
    """
    cmd = [self._hps_factory_path, '--verbose']
    if self._dev is not None:
      cmd.extend(['--dev', self._dev])
    cmd.append('print-part-ids')
    process = self._dut.Popen(cmd, stdout=self._dut.PIPE, stderr=self._dut.PIPE,
                              log=True)
    output, stderr = process.communicate()
    errors = []
    results = []
    for pattern in (MCU_ID_RE, CAMERA_ID_RE, SPI_FLASH_RE):
      match = pattern.search(output)
      if match is None:
        errors.append(f"output doesn't match {pattern.pattern!r}")
        results.append(None)
      else:
        results.append(match.group(1))

    if process.returncode != 0 or errors:
      messages = ['output:', output, 'stderr:', stderr] + errors
      if 'Failed to execute stage1' in stderr:
        messages.append(
            f"run '{self._hps_factory_path} write-stage0' before probe")
      raise HPSError('\n'.join(messages))

    return (results[0], results[1], results[2])
