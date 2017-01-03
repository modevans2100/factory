#!/usr/bin/python
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import mox
import os
import shutil
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.tools import get_version
from cros.factory.umpire.commands import update
from cros.factory.umpire import common
from cros.factory.umpire import umpire_env
from cros.factory.umpire import utils
from cros.factory.utils import file_utils


TESTDATA_DIR = os.path.join(os.path.dirname(__file__), 'testdata')
TEST_CONFIG = os.path.join(TESTDATA_DIR,
                           'minimal_empty_services_umpire.yaml')
TOOLKIT_DIR = os.path.join(TESTDATA_DIR, 'install_factory_toolkit.run')


class UmpireEnvTest(unittest.TestCase):

  def setUp(self):
    self.env = umpire_env.UmpireEnvForTest()
    self.mox = mox.Mox()

  def tearDown(self):
    self.mox.UnsetStubs()
    self.mox.VerifyAll()
    self.env.Close()

  def testLoadConfigDefault(self):
    default_path = os.path.join(self.env.base_dir, 'active_umpire.yaml')
    shutil.copy(TEST_CONFIG, default_path)

    self.env.LoadConfig()
    self.assertEqual(default_path, self.env.config_path)
    self.assertIsNotNone(self.env.shop_floor_manager)

  def testLoadConfigCustomPath(self):
    custom_path = os.path.join(self.env.base_dir, 'custom_config.yaml')
    shutil.copy(TEST_CONFIG, custom_path)

    self.env.LoadConfig(custom_path=custom_path)
    self.assertEqual(custom_path, self.env.config_path)

  def testLoadConfigNoInitShopFloorManager(self):
    default_path = os.path.join(self.env.base_dir, 'active_umpire.yaml')
    shutil.copy(TEST_CONFIG, default_path)

    self.env.LoadConfig(init_shop_floor_manager=False)
    self.assertIsNone(self.env.shop_floor_manager)

  def testStageConfigFile(self):
    config_to_stage = os.path.join(self.env.base_dir, 'to_stage.yaml')
    file_utils.TouchFile(config_to_stage)

    self.assertFalse(os.path.exists(self.env.staging_config_file))
    self.env.StageConfigFile(config_to_stage)
    self.assertTrue(os.path.exists(self.env.staging_config_file))

  def testStageConfigFileConfigAlreadyExist(self):
    # Staging config already exists.
    file_utils.TouchFile(self.env.staging_config_file)
    config_to_stage = os.path.join(self.env.base_dir, 'to_stage.yaml')
    file_utils.TouchFile(config_to_stage)

    self.assertRaisesRegexp(common.UmpireError, 'already staged',
                            self.env.StageConfigFile, config_to_stage)

  def testStageConfigFileForceStaging(self):
    # Staging config already exists.
    file_utils.TouchFile(self.env.staging_config_file)
    config_to_stage = os.path.join(self.env.base_dir, 'to_stage.yaml')
    file_utils.WriteFile(config_to_stage, 'new stage file')

    self.env.StageConfigFile(config_to_stage, force=True)
    self.assertTrue(os.path.exists(self.env.staging_config_file))
    self.assertEqual('new stage file',
                     file_utils.ReadFile(self.env.staging_config_file))

  def testStageConfigFileSourceNotFound(self):
    config_to_stage = os.path.join(self.env.base_dir, 'to_stage.yaml')

    self.assertRaisesRegexp(common.UmpireError, "doesn't exist",
                            self.env.StageConfigFile, config_to_stage)

  def testUnstageConfigFile(self):
    file_utils.TouchFile(self.env.staging_config_file)

    self.assertTrue(os.path.exists(self.env.staging_config_file))
    self.env.UnstageConfigFile()
    self.assertFalse(os.path.exists(self.env.staging_config_file))

  def testUnstageConfigFileNoStagingConfig(self):
    self.assertRaises(common.UmpireError, self.env.UnstageConfigFile)

  def testActivateConfigFile(self):
    config_to_activate = os.path.join(self.env.base_dir, 'to_activate.yaml')
    file_utils.TouchFile(config_to_activate)

    self.env.ActivateConfigFile(config_path=config_to_activate)
    self.assertTrue(os.path.exists(self.env.active_config_file))
    self.assertEqual(config_to_activate,
                     os.path.realpath(self.env.active_config_file))

  def testActivateConfigFileDefaultStaging(self):
    config_to_activate = os.path.join(self.env.base_dir, 'to_activate.yaml')
    file_utils.TouchFile(config_to_activate)
    # First prepare a staging config file.
    self.env.StageConfigFile(config_to_activate)

    self.env.ActivateConfigFile()
    self.assertTrue(os.path.exists(self.env.active_config_file))
    self.assertEqual(config_to_activate,
                     os.path.realpath(self.env.active_config_file))

  def testAddResource(self):
    resource_to_add = os.path.join(self.env.base_dir, 'some_resource')
    file_utils.WriteFile(resource_to_add, 'something')
    resource_md5 = file_utils.MD5InHex(
        resource_to_add)[:common.RESOURCE_HASH_DIGITS]

    resource_path = self.env.AddResource(resource_to_add)
    self.assertTrue(resource_path.endswith(
        '/resources/%s##%s' % ('some_resource', resource_md5)))
    self.assertTrue(os.path.exists(resource_path))

  def testAddResourceSourceNotFound(self):
    resource_to_add = os.path.join(self.env.base_dir, 'some_resource')
    self.assertRaisesRegexp(IOError, 'Missing source',
                            self.env.AddResource, resource_to_add)

  def testAddResourceSkipDuplicate(self):
    resource_to_add = os.path.join(self.env.base_dir, 'some_resource')
    file_utils.WriteFile(resource_to_add, 'something')

    resource_path = self.env.AddResource(resource_to_add)
    resource_path_duplicate = self.env.AddResource(resource_to_add)
    self.assertEqual(resource_path, resource_path_duplicate)

  def testAddResourceHashCollision(self):
    resource_to_add = os.path.join(self.env.base_dir, 'some_resource')
    file_utils.WriteFile(resource_to_add, 'something')

    resource_path = self.env.AddResource(resource_to_add)

    # Change its content to mimic hash collision case.
    file_utils.WriteFile(resource_path, 'changed')

    self.assertRaisesRegexp(common.UmpireError, 'Hash collision',
                            self.env.AddResource, resource_to_add)

  def testAddResourceFirmwareOmahaChannel(self):
    file_name = 'firmware.gz'
    resource_to_add = os.path.join(self.env.base_dir, file_name)
    file_utils.WriteFile(resource_to_add, 'firmware')
    resource_md5 = file_utils.MD5InHex(resource_to_add)[
        :common.RESOURCE_HASH_DIGITS]

    # TODO(deanliao): use real firmware.gz in which Umpire can extract
    #     version from.
    self.mox.StubOutWithMock(
        get_version, 'GetFirmwareVersionsFromOmahaChannelFile')
    BIOS_VERSION = 'bios_0.0.1'
    EC_VERSION = 'ec_0.0.2'
    PD_VERSION = 'pd_0.0.3'
    get_version.GetFirmwareVersionsFromOmahaChannelFile(
        resource_to_add).AndReturn((BIOS_VERSION, EC_VERSION, PD_VERSION))
    self.mox.ReplayAll()

    resource_path = self.env.AddResource(resource_to_add,
                                         res_type=common.ResourceType.FIRMWARE)
    expected_version = ':'.join([BIOS_VERSION, EC_VERSION, PD_VERSION])
    self.assertTrue(resource_path.endswith(
        '/resources/%s#%s#%s' % (file_name, expected_version, resource_md5)))
    self.assertTrue(os.path.exists(resource_path))

  def testAddResourceFirmware(self):
    file_name = 'chromeos-firmwareupdate'
    resource_to_add = os.path.join(self.env.base_dir, file_name)
    file_utils.WriteFile(resource_to_add, 'firmware')
    resource_md5 = file_utils.MD5InHex(resource_to_add)[
        :common.RESOURCE_HASH_DIGITS]

    # TODO(deanliao): use real chromeos-firmwareupdate in which Umpire can
    # extract version from.
    self.mox.StubOutWithMock(get_version, 'GetFirmwareVersions')
    BIOS_VERSION = 'bios_0.0.1'
    EC_VERSION = 'ec_0.0.2'
    PD_VERSION = 'pd_0.0.3'
    get_version.GetFirmwareVersions(resource_to_add).AndReturn(
        (BIOS_VERSION, EC_VERSION, PD_VERSION))
    self.mox.ReplayAll()

    resource_path = self.env.AddResource(resource_to_add,
                                         res_type=common.ResourceType.FIRMWARE)
    expected_version = ':'.join([BIOS_VERSION, EC_VERSION, PD_VERSION])
    self.assertTrue(resource_path.endswith(
        '/resources/%s#%s#%s' % (file_name, expected_version, resource_md5)))
    self.assertTrue(os.path.exists(resource_path))

  def testAddResourceRootfsRelease(self):
    file_name = 'rootfs-test.gz'
    resource_to_add = os.path.join(self.env.base_dir, file_name)
    file_utils.WriteFile(resource_to_add, 'rootfs-test')
    resource_md5 = file_utils.MD5InHex(resource_to_add)[
        :common.RESOURCE_HASH_DIGITS]

    # TODO(deanliao): use real rootfs-test.gz in which Umpire can extract
    #     version from.
    self.mox.StubOutWithMock(
        get_version, 'GetReleaseVersionFromOmahaChannelFile')
    TEST_IMAGE_VERSION = '0.0.1'
    get_version.GetReleaseVersionFromOmahaChannelFile(
        resource_to_add).AndReturn(TEST_IMAGE_VERSION)
    self.mox.ReplayAll()

    resource_path = self.env.AddResource(
        resource_to_add, res_type=common.ResourceType.ROOTFS_TEST)
    self.assertTrue(resource_path.endswith(
        '/resources/%s#%s#%s' % (file_name, TEST_IMAGE_VERSION, resource_md5)))
    self.assertTrue(os.path.exists(resource_path))

  def testAddResourceHWID(self):
    # HWID version extracted from testdata/hwid_v3_bundle.sh checksum field.
    file_name = 'hwid_v3_bundle.sh'
    hwid_version = 'a95cd8def470df2e7a8d549af887897e2d095bb0'
    resource_to_add = os.path.join(TESTDATA_DIR, file_name)
    resource_md5 = file_utils.MD5InHex(resource_to_add)[
        :common.RESOURCE_HASH_DIGITS]

    resource_path = self.env.AddResource(resource_to_add,
                                         res_type=common.ResourceType.HWID)

    self.assertTrue(resource_path.endswith(
        '/resources/%s#%s#%s' % (file_name, hwid_version, resource_md5)))
    self.assertTrue(os.path.exists(resource_path))

  def testAddResourceHWIDGzipped(self):
    # HWID version extracted from testdata/hwid.gz checksum field.
    file_name = 'hwid.gz'
    hwid_version = 'a95cd8def470df2e7a8d549af887897e2d095bb0'
    resource_to_add = os.path.join(TESTDATA_DIR, file_name)

    resource_md5 = file_utils.MD5InHex(resource_to_add)[
        :common.RESOURCE_HASH_DIGITS]

    resource_path = self.env.AddResource(resource_to_add,
                                         res_type=common.ResourceType.HWID)
    self.assertTrue(resource_path.endswith(
        '/resources/%s#%s#%s' % (file_name, hwid_version, resource_md5)))
    self.assertTrue(os.path.exists(resource_path))

  def testAddResourceToolkitNoVersion(self):
    file_name = 'install_factory_toolkit.run'
    resource_to_add = os.path.join(self.env.base_dir, file_name)
    file_utils.WriteFile(resource_to_add, 'factory_toolkit')
    resource_md5 = file_utils.MD5InHex(resource_to_add)[
        :common.RESOURCE_HASH_DIGITS]

    resource_path = self.env.AddResource(
        resource_to_add, res_type=common.ResourceType.FACTORY_TOOLKIT)

    expected_version = ''
    self.assertTrue(resource_path.endswith(
        '/resources/%s#%s#%s' % (file_name, expected_version, resource_md5)))
    self.assertTrue(os.path.exists(resource_path))

  def testGetResourcePath(self):
    resource_to_add = os.path.join(self.env.base_dir, 'some_resource')
    file_utils.WriteFile(resource_to_add, 'something')
    resource_path = self.env.AddResource(resource_to_add)
    resource_name = os.path.basename(resource_path)

    self.assertTrue(resource_path, self.env.GetResourcePath(resource_name))

  def testGetResourcePathNotFound(self):
    self.assertRaises(IOError, self.env.GetResourcePath, 'foobar')

    # Without check, just output resource_dir/resource_name
    self.assertEqual(os.path.join(self.env.resources_dir, 'foobar'),
                     self.env.GetResourcePath('foobar', check=False))

  def testInResource(self):
    # Prepare a resource file.
    resource_to_add = os.path.join(self.env.base_dir, 'some_resource')
    file_utils.WriteFile(resource_to_add, 'something')
    resource_path = self.env.AddResource(resource_to_add)
    resource_name = os.path.basename(resource_path)

    # Either full path or resource filename are okay.
    self.assertTrue(self.env.InResource(resource_path))
    self.assertTrue(self.env.InResource(resource_name))

    # Filename not in resources.
    self.assertFalse(self.env.InResource('some_resource'))
    # Dirname mismatch.
    self.assertFalse(self.env.InResource(
        os.path.join('/path/not/in/res', resource_name)))

  def PrepareBundleDeviceToolkit(self):
    """Sets a device_factory_toolkit in the default bundle.

    Returns:
      Unpacked toolkit path.
    """
    self.env.LoadConfig(custom_path=TEST_CONFIG)

    # Add the toolkit to resources and get hash value.
    updater = update.ResourceUpdater(self.env)
    updater.Update([('factory_toolkit', TOOLKIT_DIR)])
    # After updating resources, we need to reload the staging config.
    self.env.ActivateConfigFile()
    self.env.LoadConfig()

    # Get hash value to compose expected toolkit dir.
    bundle = self.env.config.GetDefaultBundle()
    toolkit_resource = bundle['resources']['device_factory_toolkit']
    toolkit_hash = utils.GetHashFromResourceName(toolkit_resource)
    return os.path.join(self.env.device_toolkits_dir, toolkit_hash)

  def testGetBundleDeviceToolkit(self):
    expected_toolkit_dir = self.PrepareBundleDeviceToolkit()

    self.assertTrue(os.path.isdir(expected_toolkit_dir))
    bundle = self.env.config.GetDefaultBundle()
    self.assertEqual(expected_toolkit_dir,
                     self.env.GetBundleDeviceToolkit(bundle['id']))

  def testGetBundleDeviceToolkitInvalidBundleID(self):
    # Same environment, but looking up an invalid bundle ID.
    self.PrepareBundleDeviceToolkit()
    self.assertIsNone(self.env.GetBundleDeviceToolkit('invalid_bundle'))

  def testGetBundleDeviceToolkitMissingToolkitPath(self):
    # Same environment, but force remove toolkit dir.
    self.PrepareBundleDeviceToolkit()
    shutil.rmtree(self.env.device_toolkits_dir)

    bundle = self.env.config.GetDefaultBundle()
    self.assertIsNone(self.env.GetBundleDeviceToolkit(bundle['id']))


if __name__ == '__main__':
  unittest.main()
