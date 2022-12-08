#!/usr/bin/env python3
# pylint: disable=protected-access
#
# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for gooftool module."""

from collections import namedtuple
import logging
import os
from tempfile import NamedTemporaryFile
import time
import unittest
from unittest import mock

from cros.factory.gooftool.bmpblk import unpack_bmpblock
from cros.factory.gooftool.common import Shell
from cros.factory.gooftool import core
from cros.factory.gooftool import cros_config
from cros.factory.gooftool import crosfw
from cros.factory.gooftool.management_engine import ManagementEngineError
from cros.factory.gooftool.management_engine import SKU
from cros.factory.gooftool import vpd
from cros.factory.test.rules import phase
from cros.factory.test.utils import model_sku_utils
from cros.factory.unittest_utils import label_utils
from cros.factory.utils import file_utils
from cros.factory.utils import pygpt
from cros.factory.utils import sys_utils
from cros.factory.utils.type_utils import Error
from cros.factory.utils.type_utils import Obj


_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')

# A stub for stdout
StubStdout = namedtuple('StubStdout', ['stdout'])


class MockMainFirmware:
  """Mock main firmware object."""

  def __init__(self, image=None):
    self.GetFileName = lambda *args, **kwargs: 'firmware'
    self.Write = lambda filename: filename == 'firmware'
    self.GetFirmwareImage = lambda: image


class MockFirmwareImage:
  """Mock firmware image object."""

  def __init__(self, section_map):
    self.has_section = lambda name: name in section_map
    self.get_section = lambda name: section_map[name]


class MockFile:
  """Mock file object."""

  def __init__(self):
    self.name = 'filename'
    self.read = lambda: 'read_results'

  def __enter__(self):
    return self

  def __exit__(self, filetype, value, traceback):
    pass


class MockPath(os.PathLike):

  def __fspath__(self):
    return 'mock_path'

  def __enter__(self):
    return self

  def __exit__(self, filetype, value, traceback):
    pass


class MockME:
  FW_NO_ME = {
      'RO_SECTION': b''
  }
  FW_ME_READ_LOCKED = {
      'SI_ME': b'\xff' * 1024
  }
  FW_ME_READ_UNLOCKED = {
      'SI_ME': b'\x55' * 1024
  }

  def GetMockedCBMEM(self, sku_flag, mode, table):
    output = (f'ME: HFSTS3                  : 0x{sku_flag:08x}\n'
              f'ME: Manufacturing Mode      : {mode}\n'
              f'ME: FW Partition Table      : {table}\n')
    return Obj(success=True, stdout=output)

class UtilTest(unittest.TestCase):
  """Unit test for core.Util."""

  def setUp(self):
    self._util = core.Util()

    # Mock out small wrapper functions that do not need unittests.
    self._util.shell = mock.Mock(Shell)
    self._util._IsDeviceFixed = mock.Mock()
    self._util.FindScript = mock.Mock()

  def testGetPrimaryDevicePath(self):
    """Test for GetPrimaryDevice."""

    self._util._IsDeviceFixed.return_value = True
    self._util.shell.return_value = StubStdout('/dev/sda')

    self.assertEqual('/dev/sda', self._util.GetPrimaryDevicePath())
    self.assertEqual('/dev/sda1', self._util.GetPrimaryDevicePath(1))
    self.assertEqual('/dev/sda2', self._util.GetPrimaryDevicePath(2))

    # also test thin callers
    self.assertEqual('/dev/sda5', self._util.GetReleaseRootPartitionPath())
    self.assertEqual('/dev/sda4', self._util.GetReleaseKernelPartitionPath())

    self._util.shell.assert_any_call('rootdev -s -d')
    self._util._IsDeviceFixed.assert_any_call('sda')

  def testGetPrimaryDevicePathNotFixed(self):
    """Test for GetPrimaryDevice when multiple primary devices are found."""

    self._util._IsDeviceFixed.return_value = False
    self._util.shell.return_value = StubStdout('/dev/sda')

    self.assertRaises(Error, self._util.GetPrimaryDevicePath)

    self._util.shell.assert_any_call('rootdev -s -d')
    self._util._IsDeviceFixed.assert_any_call('sda')

  def testFindRunScript(self):
    stub_result = lambda: None
    stub_result.success = True

    self._util.FindScript.return_value = 'script'
    self._util.shell.return_value = stub_result

    self._util.FindAndRunScript('script')
    self._util.shell.assert_called_with('script')

    self._util.FindAndRunScript('script', None)
    self._util.shell.assert_called_with('script')

    self._util.FindAndRunScript('script', ['a'])
    self._util.shell.assert_called_with('script a')

    self._util.FindAndRunScript('script', ['a', 'b'])
    self._util.shell.assert_called_with('script a b')

    self._util.FindAndRunScript('script', ['a', 'b'], ['c=d'])
    self._util.shell.assert_called_with('c=d script a b')

    self._util.FindAndRunScript('script', None, ['c=d'])
    self._util.shell.assert_called_with('c=d script')

  def testGetCrosSystem(self):
    self._util.shell.return_value = StubStdout(
        'first_flag   =   123  # fake comment\n'
        'second_flag  =   flag_2_value  # another fake comment')

    self.assertEqual({'first_flag': '123', 'second_flag': 'flag_2_value'},
                     self._util.GetCrosSystem())
    self._util.shell.assert_called_once_with('crossystem')


class GooftoolTest(unittest.TestCase):
  """Unit test for Gooftool."""

  _SIMPLE_VALID_RO_VPD_DATA = {
      'serial_number': 'A1234',
      'region': 'us',
  }

  _SIMPLE_VALID_RW_VPD_DATA = {
      'gbind_attribute': ('=CjAKIAABAgMEBQYHCAkKCwwNDg8QERITFBUWF'
                          'xgZGhscHR4fEAAaCmNocm9tZWJvb2sQhOfLlA8='),
      'ubind_attribute': ('=CjAKIAABAgMEBQYHCAkKCwwNDg8QERITFBUWF'
                          'xgZGhscHR4fEAEaCmNocm9tZWJvb2sQgdSQ-AI='),
      'rlz_embargo_end_date': '2018-03-09',
      'should_send_rlz_ping': '1',
  }

  _SIMPLE_MODEL_SKU_CONFIG_REBRAND = {
      'custom_type': 'rebrand',
      'fw_config': '90913',
  }

  _SIMPLE_MODEL_SKU_CONFIG_CUSTOM_LABEL = {
      'custom_type': 'custom_label',
      'fw_config': '90913',
  }

  def setUp(self):
    self._gooftool = core.Gooftool(
        hwid_version=3, project='chromebook', hwdb_path=_TEST_DATA_PATH)
    self._gooftool._util = mock.Mock(core.Util)
    self._gooftool._util.shell = mock.Mock(Shell)

    self._gooftool._crosfw = mock.Mock(crosfw)
    self._gooftool._unpack_bmpblock = mock.Mock(unpack_bmpblock)
    self._gooftool._vpd = mock.Mock(self._gooftool._vpd)
    self._gooftool._named_temporary_file = mock.Mock(NamedTemporaryFile)
    self._gooftool._cros_config = mock.Mock(self._gooftool._cros_config)
    self._gooftool._cros_config.GetCustomLabelTag.return_value = (True,
                                                                  'unittest')
    self._gooftool._cros_config.GetModelName.return_value = 'unittest'

    self._smart_amp_info = self._gooftool.GetSmartAmpInfo
    self._gooftool.GetSmartAmpInfo = mock.Mock(return_value=[None, None, None])

  def testVerifyECKeyWithPubkeyHash(self):
    f = MockFile()
    f.read = lambda: ''
    stub_result = lambda: None
    stub_result.success = True
    _hash = 'abcdefghijklmnopqrstuvwxyz1234567890abcd'
    self._gooftool._named_temporary_file.return_value = f
    self._gooftool._util.GetKeyHashFromFutil.return_value = _hash
    self._gooftool._util.shell.side_effect = [stub_result, stub_result]
    shell_calls = [
        mock.call('flashrom -p ec -r %s' % f.name),
        mock.call('flashrom -p ec -r %s' % f.name)]

    self._gooftool.VerifyECKey(pubkey_hash=_hash)
    self.assertRaises(Error, self._gooftool.VerifyECKey, pubkey_hash='abc123')
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)

  def testVerifyECKeyWithPubkeyPath(self):
    f = MockFile()
    f.read = lambda: ''
    pubkey = 'key.vpubk2'
    stub_result = lambda: None
    stub_result.success = True

    self._gooftool._named_temporary_file.return_value = f
    self._gooftool._util.shell.side_effect = [
        stub_result,
        Obj(success=True)]
    shell_calls = [
        mock.call('flashrom -p ec -r %s' % f.name),
        mock.call('futility show --type rwsig --pubkey %s %s' %
                  (pubkey, f.name))]

    self._gooftool.VerifyECKey(pubkey_path=pubkey)
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)

  def testLoadHWIDDatabase(self):
    db = self._gooftool.db  # Shouldn't raise any exception.

    # Assure loading DB multiple times is prevented.
    self.assertIs(self._gooftool.db, db)

  @mock.patch.object(sys_utils, 'MountPartition', autospec=True)
  @mock.patch.object(pygpt, 'GPT', autospec=True)
  def testVerifyKey(self, mock_pygpt, mock_mount):
    self._gooftool._util.GetReleaseKernelPathFromRootPartition.return_value = \
        '/dev/zero'
    self._gooftool._crosfw.LoadMainFirmware.side_effect = [
        MockMainFirmware(),
        MockMainFirmware(
            MockFirmwareImage({'GBB': b'GBB', 'FW_MAIN_A': b'MA',
                               'FW_MAIN_B': b'MB', 'VBLOCK_A': b'VA',
                               'VBLOCK_B': b'VB'}))]

    # TODO(hungte) Improve unit test scope.
    def fake_tmpexc(*unused_args, **unused_kargs):
      return ''

    class FakeGPT:

      def LoadFromFile(self):
        gpt = mock.Mock()
        gpt.IsLastPartition = mock.Mock(return_value=True)
        return gpt

    mock_mount.return_value = MockPath()

    mock_pygpt.return_value = FakeGPT()

    self._gooftool.VerifyKeys('/dev/null', _tmpexec=fake_tmpexc)
    self._gooftool._crosfw.LoadMainFirmware.assert_called()

  def testVerifySystemTime(self):
    self._gooftool._util.GetReleaseRootPartitionPath.return_value = 'root'
    self._gooftool._util.shell.return_value = Obj(
        stdout='Filesystem created:     Mon Jan 25 16:13:18 2016\n',
        success=True)

    bad_system_time = time.mktime(time.strptime('Sun Jan 24 15:00:00 2016'))
    good_system_time = time.mktime(time.strptime('Tue Jan 26 15:00:00 2016'))

    self._gooftool.VerifySystemTime(system_time=good_system_time)
    self.assertRaises(Error, self._gooftool.VerifySystemTime,
                      release_rootfs='root', system_time=bad_system_time)
    self._gooftool._util.GetReleaseRootPartitionPath.assert_called()
    self._gooftool._util.shell.assert_called_with('dumpe2fs -h root')

  def testVerifyRootFs(self):
    fake_attrs = {'test': 'value'}
    self._gooftool._util.GetPartitionDevice.return_value = 'root'
    self._gooftool._util.GetCgptAttributes.return_value = fake_attrs
    self._gooftool._util.SetCgptAttributes.return_value = None

    self._gooftool.VerifyRootFs('root3')
    self._gooftool._util.GetPartitionDevice.assert_called_once_with('root3')
    self._gooftool._util.GetCgptAttributes.assert_called_once_with('root')
    self._gooftool._util.InvokeChromeOSPostInstall.assert_called_once_with(
        'root3')
    self._gooftool._util.SetCgptAttributes.assert_called_once_with(fake_attrs,
                                                                   'root')

  @mock.patch('os.path.exists')
  @mock.patch('builtins.open')
  def testVerifyTPM(self, open_mock, path_exists_mock):
    # Mock os.path.exists to ensure that 3.18+ kernel TPM path does not exist.
    path_exists_mock.return_value = False
    open_mock_calls = [
        mock.call('/sys/class/misc/tpm0/device/enabled', encoding='utf-8',
                  mode='r'),
        mock.call('/sys/class/misc/tpm0/device/owned', encoding='utf-8',
                  mode='r'),
    ]

    # It's correct tpm sysfs status: enabled = 1, owned = 0
    open_mock.side_effect = [
        mock.mock_open(read_data='1').return_value,
        mock.mock_open(read_data='0').return_value
    ]

    # It's correct tpm manager status.
    self._gooftool._util.GetTPMManagerStatus.return_value = {
        'is_enabled': 'true',
        'is_owned': 'false',
        'is_owner_password_present': 'false'
    }

    # Should pass w/ correct tpm sysfs status + correct tpm manager status.
    self._gooftool.VerifyTPM()
    path_exists_mock.assert_called_with('/sys/class/tpm/tpm0/device')
    self.assertEqual(open_mock.call_args_list, open_mock_calls)

  @mock.patch('os.path.exists')
  @mock.patch('builtins.open')
  def testVerifyTPMWrongSysfsStatus(self, open_mock, path_exists_mock):
    # Mock os.path.exists to ensure that 3.18+ kernel TPM path does not exist.
    path_exists_mock.return_value = False

    # It's wrong tpm sysfs status: enabled = 1, owned = 1
    # The correct should be: enabled = 1, owned = 0
    open_mock.side_effect = [
        mock.mock_open(read_data='1').return_value,
        mock.mock_open(read_data='1').return_value
    ]

    # It's correct tpm manager status.
    self._gooftool._util.GetTPMManagerStatus.return_value = {
        'is_enabled': 'true',
        'is_owned': 'false',
        'is_owner_password_present': 'false'
    }

    # Should raise error w/ wrong tpm sysfs status.
    self.assertRaises(Error, self._gooftool.VerifyTPM)
    path_exists_mock.assert_called_with('/sys/class/tpm/tpm0/device')

  @mock.patch('os.path.exists')
  @mock.patch('builtins.open')
  def testVerifyTPMWrongManagerStatus(self, open_mock, path_exists_mock):
    # Mock os.path.exists to ensure that 3.18+ kernel TPM path does not exist.
    path_exists_mock.return_value = False

    # It's correct tpm sysfs status: enabled = 1, owned = 0
    open_mock.side_effect = [
        mock.mock_open(read_data='1').return_value,
        mock.mock_open(read_data='0').return_value
    ]

    # It's wrong tpm manager status, the correct should be:
    # is_enabled = true, is_owned = false, is_owner_password_present = false
    self._gooftool._util.GetTPMManagerStatus.return_value = {
        'is_enabled': 'false',
        'is_owned': 'false',
        'is_owner_password_present': 'false'
    }

    # Should raise error w/ wrong tpm manager status.
    self.assertRaises(Error, self._gooftool.VerifyTPM)
    path_exists_mock.assert_called_with('/sys/class/tpm/tpm0/device')

  def testVerifyManagementEngineLockedNoME(self):
    # No ME firmware
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware(
        MockFirmwareImage(MockME.FW_NO_ME))
    self._gooftool.VerifyManagementEngineLocked()

  def testVerifyManagementEngineLockedUnknownSKU(self):
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware(
        MockFirmwareImage(MockME.FW_ME_READ_LOCKED))

    # Raise since it is an unknown SKU
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(SKU.Unknown.flag, 'NO', 'OK')
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

  def testVerifyManagementEngineLockedConsumerSKU(self):
    # ME read locked firmware
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware(
        MockFirmwareImage(MockME.FW_ME_READ_LOCKED))

    consumer_flag = SKU.Consumer.flag
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(consumer_flag, 'NO', 'OK')
    self._gooftool.VerifyManagementEngineLocked()

    # ME read unlocked firmware
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware(
        MockFirmwareImage(MockME.FW_ME_READ_UNLOCKED))

    # Raise since the SI_ME is not 0xff
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(consumer_flag, 'NO', 'OK')
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

  def testVerifyManagementEngineLockedLiteSKU(self):
    # ME read locked firmware
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware(
        MockFirmwareImage(MockME.FW_ME_READ_LOCKED))

    lite_flag = SKU.Lite.flag
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite_flag, 'NO', 'OK')
    self._gooftool.VerifyManagementEngineLocked()

    # ME read unlocked firmware
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware(
        MockFirmwareImage(MockME.FW_ME_READ_UNLOCKED))

    # Won't raise since we don't check the SI_ME content
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite_flag, 'NO', 'OK')
    self._gooftool.VerifyManagementEngineLocked()

    # Raise since Manufacturing Mode is not NO
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite_flag, 'YES', 'OK')
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)

    # Raise since FW Partition Table is not OK
    self._gooftool._util.shell.return_value = \
      MockME().GetMockedCBMEM(lite_flag, 'NO', 'BAD')
    self.assertRaises(ManagementEngineError,
                      self._gooftool.VerifyManagementEngineLocked)


  def testClearGBBFlags(self):
    command = '/usr/share/vboot/bin/set_gbb_flags.sh 0 2>&1'

    self._gooftool._util.shell.return_value = Obj(success=True)
    self._gooftool.ClearGBBFlags()
    self._gooftool._util.shell.assert_called_with(command)

    self._gooftool._util.shell.return_value = Obj(stdout='Fail', success=False)
    self.assertRaises(Error, self._gooftool.ClearGBBFlags)
    self._gooftool._util.shell.assert_called_with(command)

  def testGenerateStableDeviceSecretSuccess(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('00' * 32 + '\n')

    self._gooftool.GenerateStableDeviceSecret()
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)
    self._gooftool._vpd.UpdateData.assert_called_once_with(
        dict(stable_device_secret_DO_NOT_SHARE='00' * 32),
        partition=vpd.VPD_READONLY_PARTITION_NAME)

  def testGenerateStableDeviceSecretNoOutput(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('')

    self.assertRaisesRegex(Error, 'Error validating device secret',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)

  def testGenerateStableDeviceSecretShortOutput(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('00' * 31)

    self.assertRaisesRegex(Error, 'Error validating device secret',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)

  def testGenerateStableDeviceSecretBadOutput(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('Error!')

    self.assertRaisesRegex(Error, 'Error validating device secret',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)

  def testGenerateStableDeviceSecretBadReleaseImageVersion(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6886.0.0'

    self.assertRaisesRegex(Error, 'Release image version',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()

  def testGenerateStableDeviceSecretVPDWriteFailed(self):
    self._gooftool._util.GetReleaseImageVersion.return_value = '6887.0.0'
    self._gooftool._util.shell.return_value = StubStdout('00' * 32 + '\n')
    self._gooftool._vpd.UpdateData.side_effect = Exception()

    self.assertRaisesRegex(Error, 'Error writing device secret',
                           self._gooftool.GenerateStableDeviceSecret)
    self._gooftool._util.GetReleaseImageVersion.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'libhwsec_client get_random 32', log=False)
    self._gooftool._vpd.UpdateData.assert_called_once_with(
        dict(stable_device_secret_DO_NOT_SHARE='00' * 32),
        partition=vpd.VPD_READONLY_PARTITION_NAME)

  def testWriteHWID(self):
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware()

    self._gooftool.WriteHWID('hwid1')
    self._gooftool._util.shell.assert_called_with(
        'futility gbb --set --hwid="hwid1" "firmware"')

    self._gooftool.WriteHWID('hwid2')
    self._gooftool._util.shell.assert_called_with(
        'futility gbb --set --hwid="hwid2" "firmware"')

    self._gooftool._crosfw.LoadMainFirmware.assert_called()

  def testVerifyWPSwitch(self):
    shell_calls = [
        mock.call('crossystem wpsw_cur'),
        mock.call('ectool flashprotect')]

    # 1st call: AP and EC wpsw are enabled.
    self._gooftool._util.shell.side_effect = [
        StubStdout('1'),
        StubStdout('Flash protect flags: 0x00000008 wp_gpio_asserted\n'
                   'Valid flags:...')]

    self._gooftool.VerifyWPSwitch()
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)

    # 2nd call: AP wpsw is disabled.
    self._gooftool._util.shell.reset_mock()
    self._gooftool._util.shell.side_effect = [StubStdout('0')]

    self.assertRaises(Error, self._gooftool.VerifyWPSwitch)
    self.assertEqual(self._gooftool._util.shell.call_args_list,
                     [shell_calls[0]])

    # 3st call: AP wpsw is enabled but EC is disabled.
    self._gooftool._util.shell.reset_mock()
    self._gooftool._util.shell.side_effect = [
        StubStdout('1'),
        StubStdout('Flash protect flags: 0x00000000\nValid flags:...')]

    self.assertRaises(Error, self._gooftool.VerifyWPSwitch)
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)

  def _SetupVPDMocks(self, ro=None, rw=None):
    """Set up mocks for vpd related tests.

    Args:
      ro: The dictionary to use for the RO VPD if set.
      rw: The dictionary to use for the RW VPD if set.
    """
    def GetAllDataSideEffect(*unused_args, **kwargs):
      if kwargs['partition'] == vpd.VPD_READONLY_PARTITION_NAME:
        return ro
      if kwargs['partition'] == vpd.VPD_READWRITE_PARTITION_NAME:
        return rw
      return None

    self._gooftool._vpd.GetAllData.side_effect = GetAllDataSideEffect

  # TODO (b/212216855)
  @label_utils.Informational
  def testVerifyVPD_AllValid(self):
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA,
                        rw=self._SIMPLE_VALID_RW_VPD_DATA)

    self._gooftool.VerifyVPD()
    self._gooftool._vpd.GetAllData.assert_any_call(
        partition=vpd.VPD_READONLY_PARTITION_NAME)
    self._gooftool._vpd.GetAllData.assert_any_call(
        partition=vpd.VPD_READWRITE_PARTITION_NAME)

  @mock.patch.object(cros_config, 'CrosConfig')
  def testVerifyVPD_NonSmartAmp(self, mock_cros_config):
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA,
                        rw=self._SIMPLE_VALID_RW_VPD_DATA)
    mock_cros_config.return_value.GetAmplifier.return_value = 'MAX98360'
    mock_cros_config.return_value.GetSoundCardInit.return_value = None
    self._gooftool.GetSmartAmpInfo = self._smart_amp_info

    # Should not fail, since MAX98360 is not a smart amplifier.
    self._gooftool.VerifyVPD()
    self._gooftool._vpd.GetAllData.assert_any_call(
        partition=vpd.VPD_READONLY_PARTITION_NAME)
    self._gooftool._vpd.GetAllData.assert_any_call(
        partition=vpd.VPD_READWRITE_PARTITION_NAME)

  @mock.patch.object(cros_config, 'CrosConfig')
  @mock.patch.object(file_utils, 'CheckPath')
  @mock.patch.object(file_utils, 'ReadFile')
  def testVerifyVPD_SmartAmpNoDSM(self, mock_file_reader, mock_path_checker,
                                  mock_cros_config):
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA,
                        rw=self._SIMPLE_VALID_RW_VPD_DATA)
    mock_cros_config.return_value.GetAmplifier.return_value = 'MAX98373'
    mock_cros_config.return_value.GetSoundCardInit.return_value = 'factory.yaml'
    mock_path_checker.return_value = True
    mock_file_reader.return_value = \
      '  temp_ctrl: ["Left ADC TEMP", "Right ADC TEMP"]'
    self._gooftool.GetSmartAmpInfo = self._smart_amp_info

    # Should fail, since dsm calib is missing.
    # Since the dictionary ordering is not deterministic, we use regex to parse
    # the error messages.
    dsm_string_regex = 'dsm_calib_(?:temp|r0)_[0-1]'
    self.assertRaisesRegex(
        Error, 'Missing required RO VPD values: (?:%s,){3}%s' %
        (dsm_string_regex, dsm_string_regex), self._gooftool.VerifyVPD)

  def testVerifyVPD_NoRegion(self):
    ro_vpd_value = self._SIMPLE_VALID_RO_VPD_DATA.copy()
    del ro_vpd_value['region']
    self._SetupVPDMocks(ro=ro_vpd_value, rw=self._SIMPLE_VALID_RW_VPD_DATA)

    # Should fail, since region is missing.
    self.assertRaisesRegex(Error, 'Missing required RO VPD values: region',
                           self._gooftool.VerifyVPD)

  def testVerifyVPD_InvalidRegion(self):
    ro_vpd_value = self._SIMPLE_VALID_RO_VPD_DATA.copy()
    ro_vpd_value['region'] = 'nonexist'
    self._SetupVPDMocks(ro=ro_vpd_value, rw=self._SIMPLE_VALID_RW_VPD_DATA)

    self.assertRaisesRegex(ValueError, 'Unknown region: "nonexist".',
                           self._gooftool.VerifyVPD)

  def testVerifyVPD_InvalidMACKey(self):
    ro_vpd_value = self._SIMPLE_VALID_RO_VPD_DATA.copy()
    ro_vpd_value['wifi_mac'] = '00:11:de:ad:be:ef'
    self._SetupVPDMocks(ro=ro_vpd_value, rw=self._SIMPLE_VALID_RW_VPD_DATA)

    self.assertRaisesRegex(KeyError,
                           'Unexpected RO VPD: wifi_mac=00:11:de:ad:be:ef.',
                           self._gooftool.VerifyVPD)

  # TODO (b/212216855)
  @label_utils.Informational
  def testVerifyVPD_InvalidRegistrationCode(self):
    rw_vpd_value = self._SIMPLE_VALID_RW_VPD_DATA.copy()
    rw_vpd_value['gbind_attribute'] = 'badvalue'
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA, rw=rw_vpd_value)

    self.assertRaisesRegex(ValueError, 'gbind_attribute is invalid:',
                           self._gooftool.VerifyVPD)

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.test.rules.phase.GetPhase')
  def testVerifyVPD_InvalidTestingRegistrationCodePVT_DOGFOOD(
      self, get_phase_mock):
    get_phase_mock.return_value = phase.PVT_DOGFOOD
    rw_vpd_value = self._SIMPLE_VALID_RW_VPD_DATA.copy()
    rw_vpd_value['gbind_attribute'] = (
        '=CjAKIP______TESTING_______-rhGkyZUn_'
        'zbTOX_9OQI_3EAAaCmNocm9tZWJvb2sQouDUgwQ=')
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA, rw=rw_vpd_value)

    self.assertRaisesRegex(ValueError, 'gbind_attribute is invalid: ',
                           self._gooftool.VerifyVPD)

  # TODO (b/212216855)
  @label_utils.Informational
  @mock.patch('cros.factory.test.rules.phase.GetPhase')
  def testVerifyVPD_InvalidTestingRegistrationCodeDVT(self, get_phase_mock):
    get_phase_mock.return_value = phase.DVT
    rw_vpd_value = self._SIMPLE_VALID_RW_VPD_DATA.copy()
    rw_vpd_value['gbind_attribute'] = (
        '=CjAKIP______TESTING_______-rhGkyZUn_'
        'zbTOX_9OQI_3EAAaCmNocm9tZWJvb2sQouDUgwQ=')
    self._SetupVPDMocks(ro=self._SIMPLE_VALID_RO_VPD_DATA, rw=rw_vpd_value)
    self._gooftool.VerifyVPD()

  def testVerifyVPD_UnexpectedValues(self):
    ro_vpd_value = self._SIMPLE_VALID_RO_VPD_DATA.copy()
    ro_vpd_value['initial_locale'] = 'en-US'
    self._SetupVPDMocks(ro=ro_vpd_value, rw=self._SIMPLE_VALID_RW_VPD_DATA)

    self.assertRaisesRegex(KeyError, 'Unexpected RO VPD: initial_locale=en-US',
                           self._gooftool.VerifyVPD)

  def testVerifyReleaseChannel_CanaryChannel(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'canary-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']

    self.assertRaisesRegex(Error,
                           'Release image channel is incorrect: canary-channel',
                           self._gooftool.VerifyReleaseChannel)

  def testVerifyReleaseChannel_DevChannel(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'dev-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']

    self._gooftool.VerifyReleaseChannel()

  def testVerifyReleaseChannel_DevChannelFailed(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'dev-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']
    enforced_channels = ['stable', 'beta']

    self.assertRaisesRegex(Error,
                           'Release image channel is incorrect: dev-channel',
                           self._gooftool.VerifyReleaseChannel,
                           enforced_channels)

  def testVerifyReleaseChannel_BetaChannel(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'beta-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']

    self._gooftool.VerifyReleaseChannel()

  def testVerifyReleaseChannel_BetaChannelFailed(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'beta-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']
    enforced_channels = ['stable']

    self.assertRaisesRegex(Error,
                           'Release image channel is incorrect: beta-channel',
                           self._gooftool.VerifyReleaseChannel,
                           enforced_channels)

  def testVerifyReleaseChannel_StableChannel(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'stable-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']

    self._gooftool.VerifyReleaseChannel()

  def testVerifyReleaseChannel_InvalidEnforcedChannels(self):
    self._gooftool._util.GetReleaseImageChannel.return_value = 'stable-channel'
    self._gooftool._util.GetAllowedReleaseImageChannels.return_value = [
        'dev', 'beta', 'stable']
    enforced_channels = ['canary']

    self.assertRaisesRegex(Error,
                           r'Enforced channels are incorrect: \[\'canary\'\].',
                           self._gooftool.VerifyReleaseChannel,
                           enforced_channels)

  # TODO (b/212216855)
  @label_utils.Informational
  def testSetFirmwareBitmapLocalePass(self):
    """Test for a normal process of setting firmware bitmap locale."""

    # Stub data from VPD for zh.
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware()
    self._SetupVPDMocks(ro=dict(region='tw'))

    f = MockFile()
    f.read = lambda: 'ja\nzh\nen'
    image_file = 'firmware'
    self._gooftool._named_temporary_file.return_value = f

    shell_calls = [
        mock.call('cbfstool %s extract -n locales -f %s -r COREBOOT' %
                  (image_file, f.name)),
        # Expect index = 1 for zh is matched.
        mock.call('crossystem loc_idx=1')]

    self._gooftool.SetFirmwareBitmapLocale()
    self._gooftool._crosfw.LoadMainFirmware.assert_any_call()
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)

  # TODO (b/212216855)
  @label_utils.Informational
  def testSetFirmwareBitmapLocaleNoCbfs(self):
    """Test for legacy firmware, which stores locale in bmpblk."""

    # Stub data from VPD for zh.
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware()
    self._SetupVPDMocks(ro=dict(region='tw'))

    f = MockFile()
    f.read = lambda: ''
    image_file = 'firmware'
    self._gooftool._named_temporary_file.return_value = f
    self._gooftool._unpack_bmpblock.return_value = {'locales': ['ja', 'zh',
                                                                'en']}
    shell_calls = [
        mock.call('cbfstool %s extract -n locales -f %s -r COREBOOT' %
                  (image_file, f.name)),
        mock.call('futility gbb -g --bmpfv=%s %s' % (f.name, image_file)),
        # Expect index = 1 for zh is matched.
        mock.call('crossystem loc_idx=1')]

    self._gooftool.SetFirmwareBitmapLocale()
    self._gooftool._crosfw.LoadMainFirmware.assert_any_call()
    self.assertEqual(self._gooftool._util.shell.call_args_list, shell_calls)
    self._gooftool._unpack_bmpblock.assert_called_once_with(f.read())

  # TODO (b/212216855)
  @label_utils.Informational
  def testSetFirmwareBitmapLocaleNoMatch(self):
    """Test for setting firmware bitmap locale without matching default locale.
    """

    # Stub data from VPD for en.
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware()
    self._SetupVPDMocks(ro=dict(region='us'))

    f = MockFile()
    # Stub for multiple available locales in the firmware bitmap, but missing
    # 'en'.
    f.read = lambda: 'ja\nzh\nfr'
    image_file = 'firmware'
    self._gooftool._named_temporary_file.return_value = f

    self.assertRaises(Error, self._gooftool.SetFirmwareBitmapLocale)
    self._gooftool._crosfw.LoadMainFirmware.assert_any_call()
    self._gooftool._util.shell.assert_called_once_with(
        'cbfstool %s extract -n locales -f %s -r COREBOOT' %
        (image_file, f.name))

  def testSetFirmwareBitmapLocaleNoVPD(self):
    """Test for setting firmware bitmap locale without default locale in VPD."""

    # VPD has no locale data.
    self._gooftool._crosfw.LoadMainFirmware.return_value = MockMainFirmware()
    self._SetupVPDMocks(ro={})

    self.assertRaises(Error, self._gooftool.SetFirmwareBitmapLocale)

  def testGetSystemDetails(self):
    """Test for GetSystemDetails to ensure it returns desired keys."""

    self._gooftool._util.shell.return_value = StubStdout('stub_value')
    self._gooftool._util.GetCrosSystem.return_value = {'key': 'value'}

    self.assertEqual(
        {
            'platform_name', 'crossystem', 'modem_status', 'ec_wp_status',
            'bios_wp_status', 'cr50_board_id', 'cr50_sn_bits', 'cr50_fw_version'
        }, set(self._gooftool.GetSystemDetails().keys()))

  def testCr50WriteFlashInfoWithCustomType(self):
    """Test for custom label field.

    Custom label field should only exist in VPD when custom type is custom
    label.
    """

    model_sku_utils.GetDesignConfig = mock.Mock()
    self._gooftool.Cr50SetBoardId = mock.Mock()
    self._gooftool._util.sys_interface = None

    # custom type is 'custom_label' but no custom label field in VPD
    config = self._SIMPLE_MODEL_SKU_CONFIG_CUSTOM_LABEL
    model_sku_utils.GetDesignConfig.return_value = config
    self._gooftool._vpd.GetValue.return_value = None

    self.assertRaisesRegex(
        Error, 'This is a custom label device, but custom_label_tag is not set '
        'in VPD.', self._gooftool.Cr50WriteFlashInfo)

    # custom type is rebrand and no custom label field in VPD
    config = self._SIMPLE_MODEL_SKU_CONFIG_REBRAND
    model_sku_utils.GetDesignConfig.return_value = config
    self.assertRaisesRegex(
        Error, 'custom_label_tag reported by cros_config and VPD does not '
        'match.  Have you reboot the device after updating VPD '
        'fields?', self._gooftool.Cr50WriteFlashInfo)


if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO)
  unittest.main()
