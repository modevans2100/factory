#!/usr/bin/env python3
#
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A CLI tool to erase, trigger re-trainining and validate the MRC cache.

The test flow of MRC cache training test: (b/249174725#comment13)

1. Erase both RECOVERY_MRC_CACHE and RW_MRC_CACHE
2. Set `crossystem recovery_request=0xC4` (VB2_RECOVERY_TRAIN_AND_REBOOT),
   cache the last line of event log and reboot.
   a. On first boot (recovery), coreboot repopulates RECOVERY_MRC_CACHE, then
      depthcharge triggers a reboot
   b. On second boot (normal), coreboot repopulates RW_MRC_CACHE
3. Check eventlog and see if caches are successfully updated.
4. Set `crossystem recovery_request=0xC4` (VB2_RECOVERY_TRAIN_AND_REBOOT),
   cache the last line of event log and reboot.
   a. On third boot (recovery), coreboot will validate RECOVERY_MRC_CACHE, then
      depthcharge triggers a reboot
   b. On fourth boot (normal), coreboot will validate RW_MRC_CACHE
5. Check eventlog and see if there's no cache update message. Coreboot won't
   update the cache if it is valid, and it only prints messages when the cache
   is updated. Finally, delete the cached boot log.

The test raises `MRCCacheUpdateError` if cache validation fails.
It also skips setting `crossystem recovery_request=0xC4` and checking
`RECOVERY_MRC_CACHE` if `RECOVERY_MRC_CACHE` is not present in FAMP.

Read more details from go/dram-init-chromebook.
"""

import argparse
import enum
import logging
import re

from cros.factory.device import device_utils
from cros.factory.test import device_data
from cros.factory.utils import type_utils

# x86 and ARM (Qualcomm) have both RECOVERY and RW MRC cache.
# ARM (Mediatek) only has RW MRC cache.
# For AMD, though it has RW MRC cache, it uses different caching mechanism
# and thus does not fit the testing flow here.
# The firmware memory section of each board is defined under
# `src/third_party/coreboot/src/mainboard/google/<board>/chromeos.fmd`.
MRC_CACHE_SECTIONS = (
    'RECOVERY_MRC_CACHE',  # For recovery mode
    'RW_MRC_CACHE',  # For normal mode
)


class Mode(str, enum.Enum):
  """MRC cache update mode."""
  Recovery = 'Recovery'
  Normal = 'Normal'


class Result(str, enum.Enum):
  """MRC cache update result."""
  Success = 'Success'
  Fail = 'Fail'
  NoUpdate = 'NoUpdate'


_MRC_CACHE_UPDATE_REGEX = (
    r'\| Memory Cache Update \| (?P<mode>\w+) \| (?P<result>\w+)')

# An event log looks like this: `<event_num> | <timestamp> | <message>`
# The event number might change across the boot if elogs is filled up.
# In this case, elog will remove some events from the beginning and re-number
# the remaining events. So we remove the event number here.
_MRC_CACHE_EVENTLOG_REGEX = r'\d+ (?P<content>.*)'

_MRC_CACHE_LAST_EVENTLOG = device_data.JoinKeys(device_data.KEY_FACTORY,
                                                'mrc_cache_last_eventlog')


def GetMRCSections(dut):
  with dut.temp.TempFile() as temp_file:
    dut.CheckCall('flashrom -p host -r %s -i FMAP' % temp_file, log=True)
    fmap_sections = dut.CheckOutput('dump_fmap -p %s' % temp_file, log=True)

  mrc_sections = []
  for section_info in fmap_sections.splitlines():
    section_name = section_info.split()[0]
    if section_name in MRC_CACHE_SECTIONS:
      mrc_sections.append(section_name)

  return mrc_sections


def HasRecoveryMRCCache(dut):
  return 'RECOVERY_MRC_CACHE' in GetMRCSections(dut)


def EraseTrainingData(dut):
  mrc_sections = GetMRCSections(dut)
  if mrc_sections:
    cmd = ['flashrom', '-p', 'host', '-E']
    for section in mrc_sections:
      cmd += ['-i', section]
    dut.CheckCall(cmd, log=True)
  logging.info('Erase success!')


def SetRecoveryRequest(dut):
  if HasRecoveryMRCCache(dut):
    # Set next boot to recovery mode to retrain RECOVERY_MRC_CACHE first.
    # And it'll reboot automatically and retrain RW_MRC_CACHE.
    dut.CheckCall('crossystem recovery_request=0xC4', log=True)
    logging.info('Set recovery_request=0xC4.')
  else:
    logging.info('No RECOVERY_MRC_CACHE found in FMAP.'
                 'Skip setting recovery_request.')


class MRCCacheUpdateError(type_utils.Error):

  def __init__(self, mode: Mode, expected: Result, actual: Result):
    message = (f'{mode.value} mode MRC cache update filed. '
               f'Expected: {expected.value}, Actual: {actual.value}')
    super().__init__(message)


class MRCCacheEventLogError(type_utils.Error):
  pass


def CacheEventLog(dut):
  """Caches the last line of the eventlog to compare with the next boot log."""
  last_line = _GetEventLog(dut)[-1]
  match = re.search(_MRC_CACHE_EVENTLOG_REGEX, last_line)
  if not match:
    raise MRCCacheEventLogError(f'Fail to parse eventlog: {last_line}')
  log_content = match.group('content')
  logging.info('Cache the last line of eventlog: %s', log_content)
  device_data.UpdateDeviceData({_MRC_CACHE_LAST_EVENTLOG: log_content})


def ClearEventlogCache():
  device_data.DeleteDeviceData(_MRC_CACHE_LAST_EVENTLOG, True)


def _GetEventLog(dut):
  # Use elogtool command instead of reading from eventlog.txt in case eventlog
  # is not flushed to file yet. See b/249407529.
  return dut.CheckOutput('elogtool list', log=True).splitlines()


def _ReadEventLog(dut):
  """Reads the eventlog reversely and returns the MRC update result.

  The update result can be 'Success', 'Fail' or 'NoUpdate'. Coreboot only
  prints eventlog message if the MRC cache succeeds or fails to update.
  This is an example output of a success update. Note that the order of system
  boot event and the cache update event might change.

  ```
  40 | 2022-10-04 01:41:38 | System boot | 61
  # The test erases cache and sets recovery_request, and user triggers reboots.
  44 | 2022-10-04 23:40:47 | Memory Cache Update | Recovery | Success
  45 | 2022-10-04 23:40:58 | System boot | 62
  # Depthcharge triggers normal reboot.
  48 | 2022-10-04 23:41:31 | Memory Cache Update | Normal | Success
  49 | 2022-10-04 23:41:42 | System boot | 63
  ...
  ```

  And this is an example output without cache update event:
  ```
  93 | 2022-10-06 20:26:15 | System boot | 74
  # The test sets recovery_request and user triggers reboot.
  98 | 2022-10-06 20:27:57 | System boot | 75
  # Depthcharge triggers normal reboot.
  101 | 2022-10-06 20:28:18 | System boot | 76
  ```

  Returns:
    A dictionary which contains the update result of RECOVERY_MRC_CACHE
    and RW_MRC_CACHE.
  """
  update_result = {
      Mode.Recovery: Result.NoUpdate,
      Mode.Normal: Result.NoUpdate,
  }

  last_boot_record = device_data.GetDeviceData(_MRC_CACHE_LAST_EVENTLOG)
  if not last_boot_record:
    raise MRCCacheEventLogError(
        'Fail to get the last boot record from device data.')
  logging.info('The last boot record is %s', last_boot_record)

  for line in reversed(_GetEventLog(dut)):
    if last_boot_record in line:
      break
    match = re.search(_MRC_CACHE_UPDATE_REGEX, line)
    if match:
      mode = Mode(match.group('mode'))
      result = Result(match.group('result'))
      logging.info('Update mode %s to %s.', mode.value, result.value)
      update_result[mode] = result

  return update_result


def VerifyTrainingData(dut, expected):
  has_recovery_mrc = HasRecoveryMRCCache(dut)
  update_result = _ReadEventLog(dut)
  actual_normal = update_result[Mode.Normal]

  if actual_normal != expected:
    raise MRCCacheUpdateError(Mode.Normal, expected, actual_normal)
  if has_recovery_mrc:
    actual_recovery = update_result[Mode.Recovery]
    if update_result[Mode.Recovery] != expected:
      raise MRCCacheUpdateError(Mode.Recovery, expected, actual_recovery)
  logging.info('Verification success!')


def main():
  logging.basicConfig(level=logging.INFO)

  parser = argparse.ArgumentParser(
      description='MRC cache tool for memory training and verification.',
      formatter_class=argparse.RawDescriptionHelpFormatter)
  subparsers = parser.add_subparsers(dest='subcommand')
  subparsers.add_parser('erase', help='Erase old training data.')
  subparsers.add_parser(
      'set_recovery_request',
      help='Set recovery request if RECOVERY_MRC_CACHE is present in FMAP. '
      'It will also cache the last boot log from elogtool for verifying the '
      'training result. User needs to trigger reboot by themselves.')
  verify_op_parser = subparsers.add_parser(
      'verify', help='Verify the training result using elogtool.')
  verify_op_parser.add_argument(
      'op', choices=('update', 'no_update'),
      help='update: Verify if cache is updated. '
      'no_update: Verify if cache is not updated. '
      'This means the cache is valid and thus no need to be updated.')
  args = parser.parse_args()

  dut = device_utils.CreateDUTInterface()
  if args.subcommand == 'erase':
    EraseTrainingData(dut)
  elif args.subcommand == 'set_recovery_request':
    SetRecoveryRequest(dut)
    CacheEventLog(dut)
  elif args.subcommand == 'verify':
    if args.op == 'update':
      VerifyTrainingData(dut, Result.Success)
    if args.op == 'no_update':
      VerifyTrainingData(dut, Result.NoUpdate)
    ClearEventlogCache()


if __name__ == '__main__':
  main()
