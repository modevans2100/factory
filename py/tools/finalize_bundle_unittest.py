#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unit tests for finalize_bundle."""

import contextlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from cros.factory.probe.functions import chromeos_firmware
from cros.factory.tools import finalize_bundle
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils


class PrepareNetbootTest(unittest.TestCase):
  """Unit tests for preparing netboot."""

  def setUp(self):
    self.temp_dir = tempfile.mkdtemp(prefix='prepare_netboot_unittest_')

  def tearDown(self):
    if os.path.exists(self.temp_dir):
      shutil.rmtree(self.temp_dir)

  def _PrepareDownloadedFiles(self,
                              bundle_builder: finalize_bundle.FinalizeBundle):
    orig_netboot_dir = os.path.join(bundle_builder.bundle_dir, 'factory_shim',
                                    'netboot')
    file_utils.TryMakeDirs(orig_netboot_dir)
    file_utils.TouchFile(
        os.path.join(bundle_builder.bundle_dir, 'factory_shim',
                     'factory_shim.bin'))
    file_utils.TouchFile(os.path.join(orig_netboot_dir, 'vmlinuz'))
    file_utils.TouchFile(os.path.join(orig_netboot_dir, 'image-test.net.bin'))
    bundle_builder.designs = ['test']

  @mock.patch(finalize_bundle.__name__ + '.Spawn', mock.Mock())
  def testPrepareNetboot_fromFactoryArchive_verifyFinalLayout(self):
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_pvt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
            'netboot_firmware': '14488.0.0',
        }, work_dir=self.temp_dir)

    bundle_builder.ProcessManifest()
    self._PrepareDownloadedFiles(bundle_builder)
    bundle_builder.PrepareNetboot()

    self.assertDictEqual(
        file_utils.HashFiles(
            os.path.join(bundle_builder.bundle_dir, 'netboot')), {
                'dnsmasq.conf':
                    '084e4b7f1040bd77555563f49f271213306b8ea5',
                'image-test.net.bin':
                    'da39a3ee5e6b4b0d3255bfef95601890afd80709',
                'tftp/chrome-bot/brya/cmdline.sample':
                    'cc137825fb0bf8ed405353b2deffb0c2a4d00b0c',
                'tftp/chrome-bot/brya/vmlinuz':
                    'da39a3ee5e6b4b0d3255bfef95601890afd80709',
            })

  @mock.patch(file_utils.__name__ + '.ExtractFile', mock.Mock())
  @mock.patch(finalize_bundle.__name__ + '.FinalizeBundle._DownloadResource')
  @mock.patch(finalize_bundle.__name__ + '.Spawn', mock.Mock())
  def testPrepareNetboot_fromFirmwareArchive_verifyFinalLayout(
      self, download_mock: mock.MagicMock):

    @contextlib.contextmanager
    def MockDownload(unused_possible_urls, unused_resource_name,
                     unused_version):
      yield (None, None)

    download_mock.side_effect = MockDownload

    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_pvt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
            'netboot_firmware': '14489.0.0',
        }, work_dir=self.temp_dir)

    bundle_builder.ProcessManifest()
    self._PrepareDownloadedFiles(bundle_builder)
    bundle_builder.PrepareNetboot()

    self.assertDictEqual(
        file_utils.HashFiles(
            os.path.join(bundle_builder.bundle_dir, 'netboot')), {
                'dnsmasq.conf':
                    '084e4b7f1040bd77555563f49f271213306b8ea5',
                'tftp/chrome-bot/brya/cmdline.sample':
                    'cc137825fb0bf8ed405353b2deffb0c2a4d00b0c',
                'tftp/chrome-bot/brya/vmlinuz':
                    'da39a3ee5e6b4b0d3255bfef95601890afd80709',
            })


class AddFirmwareUpdaterAndImagesTest(unittest.TestCase):
  """Unit tests for AddFirmwareUpdaterAndImages."""

  @staticmethod
  def MockMatchPack(unused_updater_path, dirpath, operation='pack'):
    if operation != 'unpack':
      return
    file_utils.TryMakeDirs(os.path.join(dirpath, 'images'))
    file_utils.WriteFile(
        os.path.join(dirpath, 'manifest.json'),
        json_utils.DumpStr({'test': {
            'host': {
                'image': '123'
            }
        }}))

  @staticmethod
  def MockMismatchPack(unused_updater_path, dirpath, operation='pack'):
    if operation != 'unpack':
      return
    file_utils.TryMakeDirs(os.path.join(dirpath, 'images'))
    file_utils.WriteFile(
        os.path.join(dirpath, 'manifest.json'), json_utils.DumpStr({}))

  def setUp(self):
    self.temp_dir = tempfile.mkdtemp(prefix='add_firmware_unittest_')
    self.addCleanup(shutil.rmtree, self.temp_dir)

    @contextlib.contextmanager
    def MockMount(unused_source, unused_index):
      mount_point = os.path.join(self.temp_dir, 'release_mount')
      sbin = os.path.join(mount_point, 'usr/sbin')
      file_utils.TryMakeDirs(sbin)
      file_utils.TouchFile(os.path.join(sbin, 'chromeos-firmwareupdate'))
      config_dir = os.path.join(mount_point, 'usr/share/chromeos-config/yaml')
      file_utils.TryMakeDirs(config_dir)
      file_utils.WriteFile(
          os.path.join(config_dir, 'config.yaml'),
          json_utils.DumpStr({'chromeos': {
              'configs': []
          }}))
      yield mount_point
      shutil.rmtree(mount_point)

    patcher = mock.patch(finalize_bundle.__name__ + '.MountPartition')
    patcher.start().side_effect = MockMount
    self.addCleanup(patcher.stop)

    @contextlib.contextmanager
    def MockTempdir():
      dir_path = os.path.join(self.temp_dir, 'tmp')
      file_utils.TryMakeDirs(dir_path)
      yield dir_path
      shutil.rmtree(dir_path)

    patcher = mock.patch(file_utils.__name__ + '.TempDirectory')
    patcher.start().side_effect = MockTempdir
    self.addCleanup(patcher.stop)

    patcher = mock.patch(finalize_bundle.__name__ + '._PackFirmwareUpdater')
    self.pack_mock = patcher.start()
    self.addCleanup(patcher.stop)

  def testAddFirmware_protoCrosConfigMismatch_doNotDownloadUpdater(self):
    self.pack_mock.side_effect = self.MockMismatchPack
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_proto',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    bundle_builder.ProcessManifest()
    bundle_builder.designs = ['test']
    bundle_builder.AddFirmwareUpdaterAndImages()

    self.assertDictEqual(
        file_utils.HashFiles(
            os.path.join(bundle_builder.bundle_dir, 'firmware')), {})

  def testAddFirmware_evtCrosConfigMismatch_raiseException(self):
    self.pack_mock.side_effect = self.MockMismatchPack
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    bundle_builder.ProcessManifest()
    bundle_builder.designs = ['test']
    self.assertRaisesRegex(KeyError, r'No firmware models.*',
                           bundle_builder.AddFirmwareUpdaterAndImages)

  @mock.patch(chromeos_firmware.__name__ + '.CalculateFirmwareHashes',
              mock.Mock(return_value='hash789'))
  @mock.patch(chromeos_firmware.__name__ + '.GetFirmwareKeys',
              mock.Mock(return_value='456'))
  def testAddFirmware_evtCrosConfigMatch_downloadUpdater(self):
    self.pack_mock.side_effect = self.MockMatchPack
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    bundle_builder.ProcessManifest()
    bundle_builder.designs = ['test']
    bundle_builder.AddFirmwareUpdaterAndImages()

    self.assertDictEqual(
        file_utils.HashFiles(
            os.path.join(bundle_builder.bundle_dir, 'firmware')),
        {'chromeos-firmwareupdate': 'da39a3ee5e6b4b0d3255bfef95601890afd80709'})


if __name__ == '__main__':
  unittest.main()
