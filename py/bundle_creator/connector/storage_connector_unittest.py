# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import unittest
from unittest import mock

from cros.factory.bundle_creator.connector import storage_connector


class StorageConnectorTest(unittest.TestCase):

  _CLOUD_PROJECT_ID = 'fake-project-id'
  _BUCKET_NAME = 'fake-bucket'
  _BUNDLE_PATH = '/tmp/fake_bundle_path'
  _EXPECTED_FILENAME = (
      'factory_bundle_project_20220508_0000_proto_00000.tar.bz2')

  def setUp(self):
    self._bundle_metadata = storage_connector.StorageBundleMetadata(
        doc_id='FakeDocId', email='foo@bar', board='board', project='project',
        phase='proto', toolkit_version='11111.0.0',
        test_image_version='22222.0.0', release_image_version='33333.0.0')

    mock_datetime_patcher = mock.patch('datetime.datetime')
    mock_datetime_patcher.start().now.return_value = datetime.datetime(
        2022, 5, 8, 0, 0)
    self.addCleanup(mock_datetime_patcher.stop)

    self._mock_blob = mock.Mock()
    self._mock_bucket = mock.Mock()
    self._mock_bucket.blob.return_value = self._mock_blob
    mock_storage_patcher = mock.patch('google.cloud.storage.Client')
    mock_client = mock_storage_patcher.start().return_value
    mock_client.get_bucket.return_value = self._mock_bucket
    self.addCleanup(mock_storage_patcher.stop)

    self._connector = storage_connector.StorageConnector(
        self._CLOUD_PROJECT_ID, self._BUCKET_NAME)

  def testUploadCreatedBundle_verifyInitializesBlobWithExpectedValues(self):
    self._connector.UploadCreatedBundle(self._BUNDLE_PATH,
                                        self._bundle_metadata)

    self.assertEqual(self._mock_bucket.blob.call_args.args[0],
                     f'board/project/{self._EXPECTED_FILENAME}')
    self.assertEqual(self._mock_blob.content_disposition,
                     f'filename="{self._EXPECTED_FILENAME}"')
    self._mock_blob.upload_from_filename.assert_called_once_with(
        self._BUNDLE_PATH)

  def testUploadCreatedBundle_verifyGrantUserReadPermission(self):
    mock_acl_entity = mock.Mock()
    self._mock_blob.acl.entity.return_value = mock_acl_entity

    self._connector.UploadCreatedBundle(self._BUNDLE_PATH,
                                        self._bundle_metadata)

    self.assertEqual(self._mock_blob.acl.entity.call_args.args,
                     ('user', 'foo@bar'))
    mock_acl_entity.grant_read.assert_called_once()
    self._mock_blob.acl.save.assert_called_once()

  def testUploadCreatedBundle_withoutFirmwareSource_verifyUpdateMetadata(self):
    created_timestamp = 1651939200
    self._mock_blob.time_created.timestamp.return_value = created_timestamp

    self._connector.UploadCreatedBundle(self._BUNDLE_PATH,
                                        self._bundle_metadata)

    self.assertEqual(
        self._mock_blob.metadata, {
            'Bundle-Creator': 'foo@bar',
            'Phase': 'proto',
            'Tookit-Version': '11111.0.0',
            'Test-Image-Version': '22222.0.0',
            'Release-Image-Version': '33333.0.0',
            'User-Request-Doc-Id': 'FakeDocId',
            'Time-Created': created_timestamp,
        })
    self._mock_blob.update.assert_called_once()

  def testUploadCreatedBundle_withFirmwareSource_verifyUpdateMetadata(self):
    created_timestamp = 1651939200
    self._mock_blob.time_created.timestamp.return_value = created_timestamp
    self._bundle_metadata.firmware_source = '44444.0.0'

    self._connector.UploadCreatedBundle(self._BUNDLE_PATH,
                                        self._bundle_metadata)

    self.assertEqual(
        self._mock_blob.metadata, {
            'Bundle-Creator': 'foo@bar',
            'Phase': 'proto',
            'Tookit-Version': '11111.0.0',
            'Test-Image-Version': '22222.0.0',
            'Release-Image-Version': '33333.0.0',
            'User-Request-Doc-Id': 'FakeDocId',
            'Time-Created': created_timestamp,
            'Firmware-Source': '44444.0.0',
        })
    self._mock_blob.update.assert_called_once()

  def testUploadCreatedBundle_returnsExpectedGsPath(self):
    gs_path = self._connector.UploadCreatedBundle(self._BUNDLE_PATH,
                                                  self._bundle_metadata)

    self.assertEqual(
        gs_path, f'gs://fake-bucket/board/project/{self._EXPECTED_FILENAME}')


if __name__ == '__main__':
  unittest.main()