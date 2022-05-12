# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import unittest
from unittest import mock

from google.api_core.datetime_helpers import DatetimeWithNanoseconds
from google.cloud import firestore  # pylint: disable=no-name-in-module,import-error
import pytz

from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module


class FirestoreConnectorTest(unittest.TestCase):

  _CLOUD_PROJECT_ID = 'fake-project-id'
  _PROJECT = 'project'
  _HAS_FIRMWARE_SETTING_VALUE = ['BIOS']
  _EMPTY_USER_REQUEST_DOC_ID = 'EmptyRequestDocId'
  _FIRESTORE_CURRENT_DATETIME = DatetimeWithNanoseconds(2022, 6, 8, 0, 0,
                                                        tzinfo=pytz.UTC)

  def setUp(self):
    self._create_bundle_rpc_request = factorybundle_pb2.CreateBundleRpcRequest()
    self._create_bundle_rpc_request.board = 'board'
    self._create_bundle_rpc_request.project = 'project'
    self._create_bundle_rpc_request.phase = 'proto'
    self._create_bundle_rpc_request.toolkit_version = '11111.0.0'
    self._create_bundle_rpc_request.test_image_version = '12222.0.0'
    self._create_bundle_rpc_request.release_image_version = '13333.0.0'
    self._create_bundle_rpc_request.email = 'foo@bar'

    mock_datetime_patcher = mock.patch(
        'cros.factory.bundle_creator.connector.firestore_connector.datetime')
    mock_datetime_patcher.start().now.return_value = datetime.datetime(
        2022, 6, 8, 0, 0)
    self.addCleanup(mock_datetime_patcher.stop)

    self._connector = firestore_connector.FirestoreConnector(
        self._CLOUD_PROJECT_ID)
    self._connector.ClearCollection('has_firmware_settings')
    self._connector.ClearCollection('user_requests')

    client = firestore.Client(project=self._CLOUD_PROJECT_ID)
    self._has_firmware_setting_col = client.collection('has_firmware_settings')
    self._user_requests_col = client.collection('user_requests')
    self._user_requests_col.document(self._EMPTY_USER_REQUEST_DOC_ID).set({})

  def testGetHasFirmwareSettingByProject_succeed_returnsExpectedValues(self):
    self._has_firmware_setting_col.document(self._PROJECT).set(
        {'has_firmware': self._HAS_FIRMWARE_SETTING_VALUE})

    has_firmware_setting = (
        self._connector.GetHasFirmwareSettingByProject(self._PROJECT))

    self.assertEqual(has_firmware_setting, self._HAS_FIRMWARE_SETTING_VALUE)

  def testGetHasFirmwareSettingByProject_keyError_returnsNone(self):
    self._has_firmware_setting_col.document(self._PROJECT).set({})

    has_firmware_setting = (
        self._connector.GetHasFirmwareSettingByProject(self._PROJECT))

    self.assertIsNone(has_firmware_setting)

  def testGetHasFirmwareSettingByProject_documentNotExists_returnsNone(self):
    has_firmware_setting = (
        self._connector.GetHasFirmwareSettingByProject(self._PROJECT))

    self.assertIsNone(has_firmware_setting)

  def testCreateUserRequest_succeed_verifiesCreatedDocument(self):
    doc_id = self._connector.CreateUserRequest(self._create_bundle_rpc_request)

    expected_doc = {
        'email':
            self._create_bundle_rpc_request.email,
        'board':
            self._create_bundle_rpc_request.board,
        'project':
            self._create_bundle_rpc_request.project,
        'phase':
            self._create_bundle_rpc_request.phase,
        'toolkit_version':
            self._create_bundle_rpc_request.toolkit_version,
        'test_image_version':
            self._create_bundle_rpc_request.test_image_version,
        'release_image_version':
            self._create_bundle_rpc_request.release_image_version,
        'status':
            self._connector.USER_REQUEST_STATUS_NOT_STARTED,
        'request_time':
            self._FIRESTORE_CURRENT_DATETIME,
    }
    doc = self._connector.GetUserRequestDocument(doc_id)
    self.assertEqual(doc, expected_doc)

  def testCreateUserRequest_hasFirmwareSource_verifiesFirmwareSourceValue(self):
    self._create_bundle_rpc_request.firmware_source = '14444.0.0'

    doc_id = self._connector.CreateUserRequest(self._create_bundle_rpc_request)

    doc = self._connector.GetUserRequestDocument(doc_id)
    self.assertEqual(doc['firmware_source'],
                     self._create_bundle_rpc_request.firmware_source)

  def testUpdateUserRequestStatus_succeed_verifiesDocStatus(self):
    status = self._connector.USER_REQUEST_STATUS_SUCCEEDED

    self._connector.UpdateUserRequestStatus(self._EMPTY_USER_REQUEST_DOC_ID,
                                            status)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['status'], status)

  def testUpdateUserRequestStartTime_succeed_verifiesDocStartTime(self):
    self._connector.UpdateUserRequestStartTime(self._EMPTY_USER_REQUEST_DOC_ID)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['start_time'], self._FIRESTORE_CURRENT_DATETIME)

  def testUpdateUserRequestEndTime_succeed_verifiesDocEndTime(self):
    self._connector.UpdateUserRequestEndTime(self._EMPTY_USER_REQUEST_DOC_ID)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['end_time'], self._FIRESTORE_CURRENT_DATETIME)

  def testUpdateUserRequestErrorMessage_succeed_verifiesErrorMessage(self):
    error_msg = 'fake_error_message'

    self._connector.UpdateUserRequestErrorMessage(
        self._EMPTY_USER_REQUEST_DOC_ID, error_msg)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['error_message'], error_msg)

  def testUpdateUserRequestGsPath_succeed_verifiesGsPath(self):
    gs_path = 'gs://fake_path'

    self._connector.UpdateUserRequestGsPath(self._EMPTY_USER_REQUEST_DOC_ID,
                                            gs_path)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['gs_path'], gs_path)

  def testGetUserRequestsByEmail_succeed_returnsExpectedDocuments(self):
    email = 'foo@bar'
    self._user_requests_col.document('doc_1').set({
        'email': email,
        'request_time': datetime.datetime(2022, 5, 20, 0, 0)
    })
    self._user_requests_col.document('doc_2').set({
        'email': email,
        'request_time': datetime.datetime(2022, 5, 21, 0, 0)
    })
    self._user_requests_col.document('doc_3').set({
        'email': 'foo2@bar',
        'request_time': datetime.datetime(2022, 5, 22, 0, 0)
    })

    user_requests = self._connector.GetUserRequestsByEmail(email)

    self.assertEqual(user_requests, [{
        'email':
            email,
        'request_time':
            DatetimeWithNanoseconds(2022, 5, 21, 0, 0, tzinfo=pytz.UTC)
    }, {
        'email':
            email,
        'request_time':
            DatetimeWithNanoseconds(2022, 5, 20, 0, 0, tzinfo=pytz.UTC)
    }])


if __name__ == '__main__':
  unittest.main()
