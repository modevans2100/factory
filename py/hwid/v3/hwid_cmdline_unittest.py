#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
import unittest
from unittest import mock

from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import hwid_cmdline
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.utils import file_utils
from cros.factory.utils import type_utils


HWIDException = common.HWIDException


class FakeOutput:

  def __init__(self):
    self.data = ''

  def __call__(self, msg):
    self.data += msg + '\n'


class TestCaseBaseWithFakeOutput(unittest.TestCase):

  def setUp(self):
    self.orig_output = hwid_cmdline.Output
    hwid_cmdline.Output = FakeOutput()

  def tearDown(self):
    hwid_cmdline.Output = self.orig_output


class OutputObjectTest(TestCaseBaseWithFakeOutput):

  def testYamlFormat(self):
    hwid_cmdline.OutputObject(
        mock.MagicMock(json_output=False), {
            'aaa': ['bbb', 'ccc'],
            'xxx': 3
        })
    self.assertEqual(
        yaml.safe_load(hwid_cmdline.Output.data), {
            'aaa': ['bbb', 'ccc'],
            'xxx': 3
        })

  def testJsonFormat(self):
    hwid_cmdline.OutputObject(
        mock.MagicMock(json_output=True), {
            'aaa': ['bbb', 'ccc'],
            'xxx': 3
        })
    self.assertEqual(
        json.loads(hwid_cmdline.Output.data), {
            'aaa': ['bbb', 'ccc'],
            'xxx': 3
        })


class TestCaseBaseWithMockedOutputObject(unittest.TestCase):

  def setUp(self):
    self.orig_output_object = hwid_cmdline.OutputObject
    hwid_cmdline.OutputObject = mock.MagicMock()

  def tearDown(self):
    hwid_cmdline.OutputObject = self.orig_output_object


class ObtainHWIDMaterialTest(unittest.TestCase):

  def setUp(self):
    super().setUp()

    patcher = mock.patch('cros.factory.hwid.v3.hwid_utils.GetVPDData')
    self._mock_get_vpd_data = patcher.start()
    self._mock_get_vpd_data.return_value = {
        'some_vpd_data': 'some_value'
    }
    self.addCleanup(patcher.stop)

    patcher = mock.patch('cros.factory.hwid.v3.hwid_utils.GetDeviceInfo')
    self._mock_get_device_info = patcher.start()
    self._mock_get_device_info.return_value = {
        'some_device_info': 'some_value'
    }
    self.addCleanup(patcher.stop)

    patcher = mock.patch('cros.factory.hwid.v3.hwid_utils.GetProbedResults')
    self._mock_get_probed_results = patcher.start()
    self._mock_get_probed_results.return_value = {
        'some_pr': 'some_value'
    }
    self.addCleanup(patcher.stop)

    patcher = mock.patch('cros.factory.utils.sys_utils.InCrOSDevice')
    self._mock_in_cros_device = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch(
        'cros.factory.hwid.v3.hwid_utils.GetSkuIdsFromCrosConfig')
    self._mock_get_sku_ids_from_cros_config = patcher.start()
    self.addCleanup(patcher.stop)

    self._probed_results_file = file_utils.CreateTemporaryFile()
    self.addCleanup(lambda: file_utils.TryUnlink(self._probed_results_file))
    file_utils.WriteFile(self._probed_results_file, '{"storage": {}}')

    self._hwid_material_file = file_utils.CreateTemporaryFile()
    self.addCleanup(lambda: file_utils.TryUnlink(self._hwid_material_file))
    file_utils.WriteFile(
        self._hwid_material_file,
        hwid_cmdline.HWIDMaterial(
            probed_results={}, device_info={}, vpd={},
            framework_version=common.OLDEST_FRAMEWORK_VERSION).DumpStr())

    self._options = type_utils.Obj(project='test_project',
                                   device_info_file=None, vpd_data_file=None,
                                   run_vpd=False, config_yaml=None)

  def testSpecifyBothRunVPDAndVPDDataFile(self):
    self._options.vpd_data_file = 'a_vpd_data_file'
    self._options.run_vpd = True

    with self.assertRaises(ValueError):
      hwid_cmdline.ObtainHWIDMaterial(self._options)

  def testInCrOSDeviceThenDeprecateProbedResultsFile(self):
    self._mock_in_cros_device.return_value = True

    self._options.probed_results_file = self._probed_results_file

    with self.assertRaises(ValueError):
      hwid_cmdline.ObtainHWIDMaterial(self._options)

  def testHasHWIDMaterialThenDeprecateProbedResultsFile(self):
    self._mock_in_cros_device.return_value = False

    self._options.probed_results_file = self._probed_results_file
    self._options.material_file = self._hwid_material_file

    with self.assertRaises(ValueError):
      hwid_cmdline.ObtainHWIDMaterial(self._options)

  def testLegacyUseCaseMissingRequiredDeviceInfoFile(self):
    self._mock_in_cros_device.return_value = False
    self._options.probed_results_file = self._probed_results_file

    with self.assertRaises(ValueError):
      hwid_cmdline.ObtainHWIDMaterial(self._options)

  def testLegacyUseCaseMissingRequiredProbedResultsFile(self):
    self._mock_in_cros_device.return_value = False
    self._options.probed_results_file = None
    self._options.device_info_file = 'a_device_info_file'

    with self.assertRaises(ValueError):
      hwid_cmdline.ObtainHWIDMaterial(self._options)

  def testLegacyUseCaseWrongUseOfProbedResultsFile(self):
    self._mock_in_cros_device.return_value = False
    file_utils.WriteFile(self._probed_results_file,
                         file_utils.ReadFile(self._hwid_material_file))
    self._options.probed_results_file = self._probed_results_file
    self._options.device_info_file = 'device_info_file'

    with self.assertRaises(ValueError):
      hwid_cmdline.ObtainHWIDMaterial(self._options)

  def testNoBaseHWIDMaterialSucceed(self):
    self._mock_in_cros_device.return_value = True
    self._mock_get_sku_ids_from_cros_config.return_value = [11, 22, 33, 44]
    self._options.device_info_file = 'a_device_info_file'
    self._options.run_vpd = True

    ret = hwid_cmdline.ObtainHWIDMaterial(self._options)

    self._mock_get_probed_results.assert_called_once_with(
        infile=None, project='test_project')
    self._mock_get_device_info.assert_called_once_with(
        infile='a_device_info_file')
    self._mock_get_vpd_data.assert_called_once_with(infile=None, run_vpd=True)
    expected_ret = hwid_cmdline.HWIDMaterial(
        probed_results=self._mock_get_probed_results.return_value,
        device_info=self._mock_get_device_info.return_value,
        vpd=self._mock_get_vpd_data.return_value,
        sku_ids=self._mock_get_sku_ids_from_cros_config.return_value,
        framework_version=common.FRAMEWORK_VERSION)
    self.assertEqual(ret, expected_ret)

  def testHasBaseHWIDMaterialOverrideSucceed(self):
    self._mock_in_cros_device.return_value = True

    self._options.material_file = self._hwid_material_file
    self._options.device_info_file = 'a_device_info_file'
    self._options.run_vpd = True

    ret = hwid_cmdline.ObtainHWIDMaterial(self._options)

    self._mock_get_device_info.assert_called_once_with(
        infile='a_device_info_file')
    self._mock_get_vpd_data.assert_called_once_with(infile=None, run_vpd=True)
    expected_ret = hwid_cmdline.HWIDMaterial(
        probed_results={}, device_info=self._mock_get_device_info.return_value,
        vpd=self._mock_get_vpd_data.return_value, sku_ids=None,
        framework_version=common.OLDEST_FRAMEWORK_VERSION)
    self.assertEqual(ret, expected_ret)

    sku_ids = [11, 22, 33, 44]
    file_utils.WriteFile(
        self._hwid_material_file,
        hwid_cmdline.HWIDMaterial(
            probed_results={}, device_info={}, vpd={}, sku_ids=sku_ids,
            framework_version=common.OLDEST_FRAMEWORK_VERSION).DumpStr())
    ret = hwid_cmdline.ObtainHWIDMaterial(self._options)
    expected_ret = hwid_cmdline.HWIDMaterial(
        probed_results={}, device_info=self._mock_get_device_info.return_value,
        vpd=self._mock_get_vpd_data.return_value, sku_ids=sku_ids,
        framework_version=common.OLDEST_FRAMEWORK_VERSION)
    self.assertEqual(ret, expected_ret)


class BuildDatabaseWrapperTest(unittest.TestCase):

  @mock.patch('cros.factory.hwid.v3.builder.DatabaseBuilder')
  @mock.patch('cros.factory.hwid.v3.hwid_cmdline.ObtainHWIDMaterial')
  def testNormal(self, obtain_hwid_material_mock, build_database_mock):
    with file_utils.TempDirectory() as path:
      options = mock.MagicMock()
      options.project = 'mock'
      options.hwid_db_path = path
      options.add_default_comp = ['a', 'b']
      options.add_null_comp = ['c', 'd']
      options.add_regions = ['us', 'tw', 'jp']
      options.region_field_name = 'test_region_field'
      options.minimal = False
      options.auto_decline_essential_prompt = []
      options.fill_combinations = []
      options.skip_update_by_material_file = False

      hwid_cmdline.BuildDatabaseWrapper(options)

      # Constructor.
      build_database_mock.FromEmpty.assert_called_with(
          project=options.project, image_name=options.image_id,
          auto_decline_essential_prompt=options.auto_decline_essential_prompt)
      instance = build_database_mock.FromEmpty.return_value

      # Uprev the framework version.
      instance.UprevFrameworkVersion.assert_called_with(
          obtain_hwid_material_mock.return_value.framework_version)

      # Update default/null components.
      instance.AddDefaultComponent.assert_has_calls(
          [mock.call('a'), mock.call('b')], any_order=True)
      instance.AddNullComponent.assert_has_calls(
          [mock.call('c'), mock.call('d')], any_order=True)
      instance.AddRegions.assert_called_once_with(options.add_regions,
                                                  options.region_field_name)

      # Update by the probed results.
      instance.UpdateByProbedResults.assert_called_with(
          obtain_hwid_material_mock.return_value.probed_results,
          obtain_hwid_material_mock.return_value.device_info,
          obtain_hwid_material_mock.return_value.vpd,
          obtain_hwid_material_mock.return_value.sku_ids,
          image_name=options.image_id)

  def testBuildMinimalHWIDDBConflictOptions(self):
    with file_utils.TempDirectory() as path:
      options = type_utils.Obj(
          project='FOO',
          image_id='EVT',
          add_default_comp=None,
          add_null_comp=None,
          add_regions=None,
          material_file='/path/to/material.yaml',
          probed_results_file=None,
          hwid_db_path=path,
          minimal=True,
          device_info_file=None,
          vpd_data_file=None,
          run_vpd=False,
          config_yaml=None,
          auto_decline_essential_prompt=[],
          fill_combinations=[],
          skip_update_by_material_file=False,
      )
      with self.assertRaises(ValueError):
        hwid_cmdline.BuildDatabaseWrapper(options)

  @mock.patch('cros.factory.hwid.v3.builder.ChecksumUpdater', return_value=None)
  def testBuildMinimalHWIDDBFile(self, unused_checksum_updater):
    with file_utils.TempDirectory() as path:
      options = type_utils.Obj(
          project='FOO',
          image_id='EVT',
          add_default_comp=None,
          add_null_comp=None,
          add_regions=None,
          material_file=None,
          probed_results_file=None,
          hwid_db_path=path,
          minimal=True,
          device_info_file=None,
          vpd_data_file=None,
          run_vpd=False,
          config_yaml=None,
          auto_decline_essential_prompt=[],
          fill_combinations=[],
          skip_update_by_material_file=False,
      )
      hwid_cmdline.BuildDatabaseWrapper(options)

      db_file_path = os.path.join(path, 'FOO')
      db = database.Database.LoadFile(db_file_path, verify_checksum=False)
      expected_db = database.WritableDatabase(
          'FOO', database.EncodingPatterns({0: 'default'}),
          database.ImageId({0: 'EVT'}),
          database.Pattern([{
              'encoding_scheme': 'base8192',
              'fields': [],
              'image_ids': [0],
          }]), database.EncodedFields({'region_field': {
              0: {
                  'region': []
              }
          }}), database.Components(yaml.safe_load('region: !region_component')),
          database.Rules([]), None, db.framework_version)

      self.assertEqual(expected_db, db)


class UpdateDatabaseWrapperTest(unittest.TestCase):

  @mock.patch('cros.factory.hwid.v3.builder.DatabaseBuilder')
  @mock.patch('cros.factory.hwid.v3.hwid_cmdline.ObtainHWIDMaterial')
  def testNormal(self, obtain_hwid_material_mock, build_database_mock):
    with file_utils.TempDirectory() as path:
      options = mock.MagicMock()
      options.hwid_db_path = path
      options.add_default_comp = ['a', 'b']
      options.add_null_comp = ['c', 'd']
      options.add_regions = ['us', 'tw', 'jp']
      options.region_field_name = 'test_region_field'
      options.project = 'proj'
      options.minimal = False
      options.skip_update_by_material_file = False
      options.fill_combinations = [
          hwid_cmdline.ComponentCombinationFillingRequest('camera_field', 2)
      ]

      hwid_cmdline.UpdateDatabaseWrapper(options)

      # Constructor.
      build_database_mock.FromFilePath.assert_called_with(
          db_path=os.path.join(path, 'PROJ'))
      instance = build_database_mock.FromFilePath.return_value

      # Update default/null components.
      instance.AddDefaultComponent.assert_has_calls(
          [mock.call('a'), mock.call('b')], any_order=True)
      instance.AddNullComponent.assert_has_calls(
          [mock.call('c'), mock.call('d')], any_order=True)
      instance.AddRegions.assert_called_once_with(options.add_regions,
                                                  options.region_field_name)

      # Update by the probed results.
      instance.UpdateByProbedResults.assert_called_with(
          obtain_hwid_material_mock.return_value.probed_results,
          obtain_hwid_material_mock.return_value.device_info,
          obtain_hwid_material_mock.return_value.vpd,
          obtain_hwid_material_mock.return_value.sku_ids,
          image_name=options.image_id)

      # Extend full component combination in specified encoded fields.
      instance.ExtendEncodedFieldToFullCombination.assert_called_with(
          'camera_field', 2)


class GenerateHWIDWrapperTest(TestCaseBaseWithMockedOutputObject):

  @mock.patch('cros.factory.hwid.v3.hwid_utils.GenerateHWID')
  @mock.patch('cros.factory.hwid.v3.hwid_cmdline.ObtainHWIDMaterial')
  def testNormal(self, obtain_hwid_material_mock, generate_hwid_mock):
    options = mock.MagicMock()
    hwid_cmdline.GenerateHWIDWrapper(options)

    hwid_material = obtain_hwid_material_mock.return_value
    generate_hwid_mock.assert_called_once_with(
        options.database, hwid_material.probed_results,
        hwid_material.device_info, hwid_material.vpd, options.rma_mode,
        options.with_configless_fields, options.brand_code,
        allow_mismatched_components=options.allow_mismatched_components,
        use_name_match=options.use_name_match)

    identity = generate_hwid_mock.return_value
    hwid_cmdline.OutputObject.assert_called_once_with(
        options, {
            'encoded_string': identity.encoded_string,
            'binary_string': identity.binary_string,
            'database_checksum': options.database.checksum
        })


class GenerateTestHWIDWrapperTest(unittest.TestCase):
  """The unittest of GenerateTestHWIDWrapper."""

  @mock.patch('cros.factory.hwid.v3.hwid_utils.GenerateTestHWID')
  @mock.patch('cros.factory.hwid.v3.hwid_cmdline.Output')
  def testNormal(self, output_mock: mock.MagicMock,
                 generate_test_hwid_mock: mock.MagicMock):
    generate_test_hwid_mock.return_value = 'TEST-ZZCR TEST 9373'
    options = mock.MagicMock()
    hwid_cmdline.GenerateTestHWIDWrapper(options)

    generate_test_hwid_mock.assert_called_once_with(options.project,
                                                    options.brand_code)
    output_mock.assert_called_once_with('TEST-ZZCR TEST 9373')


class DecodeHWIDWrapperTest(TestCaseBaseWithMockedOutputObject):

  @mock.patch(
      'cros.factory.hwid.v3.hwid_utils.DecodeHWID',
      return_value=(mock.MagicMock(), mock.MagicMock(), mock.MagicMock()))
  def testNormal(self, decode_hwid_mock):
    options = mock.MagicMock()
    hwid_cmdline.DecodeHWIDWrapper(options)

    decode_hwid_mock.assert_called_once_with(options.database, options.hwid)
    identity, bom, configless = decode_hwid_mock.return_value

    hwid_cmdline.OutputObject.assert_called_once_with(
        options, {
            'project': identity.project,
            'binary_string': identity.binary_string,
            'image_id': bom.image_id,
            'components': bom.components,
            'brand_code': identity.brand_code,
            'configless': configless
        })


class VerifyHWIDWrapperTest(TestCaseBaseWithFakeOutput):

  @mock.patch('cros.factory.hwid.v3.hwid_utils.VerifyHWID')
  @mock.patch('cros.factory.hwid.v3.hwid_cmdline.ObtainHWIDMaterial')
  def testNormal(self, obtain_hwid_material_mock, verify_hwid_mock):
    options = mock.MagicMock()
    hwid_cmdline.VerifyHWIDWrapper(options)

    hwid_material = obtain_hwid_material_mock.return_value

    verify_hwid_mock.assert_called_once_with(
        options.database, options.hwid, hwid_material.probed_results,
        hwid_material.device_info, hwid_material.vpd, options.rma_mode,
        current_phase=options.phase,
        allow_mismatched_components=options.allow_mismatched_components,
        pvt_component_status_check=options.pvt_component_status_check)

  @mock.patch('cros.factory.hwid.v3.hwid_utils.VerifyHWID',
              side_effect=HWIDException('verify fail'))
  @mock.patch('cros.factory.hwid.v3.hwid_cmdline.ObtainHWIDMaterial')
  def testVerifyFailed(self, unused_obtain_hwid_material_mock,
                       unused_verify_hwid_mock):
    self.assertRaises(HWIDException, hwid_cmdline.VerifyHWIDWrapper,
                      mock.MagicMock())


class ListComponentsWrapperTest(TestCaseBaseWithMockedOutputObject):

  @mock.patch('cros.factory.hwid.v3.hwid_utils.ListComponents')
  def testNormal(self, list_components_mock):
    options = mock.MagicMock()
    hwid_cmdline.ListComponentsWrapper(options)

    list_components_mock.assert_called_once_with(options.database,
                                                 options.comp_class)
    hwid_cmdline.OutputObject.assert_called_once_with(
        options, list_components_mock.return_value)


class EnumerateHWIDWrapperTest(TestCaseBaseWithFakeOutput):

  @mock.patch('cros.factory.hwid.v3.hwid_utils.EnumerateHWID', return_value={
      'HWID1': 'bbb',
      'HWID2': 'aaa'
  })
  def testDefault(self, unused_enumerate_hwid_mock):
    hwid_cmdline.EnumerateHWIDWrapper(mock.MagicMock(comp=None, no_bom=False))

    self.assertEqual(hwid_cmdline.Output.data, 'HWID1: bbb\nHWID2: aaa\n')

  @mock.patch('cros.factory.hwid.v3.hwid_utils.EnumerateHWID', return_value={})
  def testComp(self, enumerate_hwid_mock):
    options = mock.MagicMock(comp=['aaa=bbb', 'ccc=ddd,eee'])
    hwid_cmdline.EnumerateHWIDWrapper(options)

    enumerate_hwid_mock.assert_called_once_with(
        options.database,
        image_id=options.database.GetImageIdByName.return_value,
        status=options.status, comps={
            'aaa': ['bbb'],
            'ccc': ['ddd', 'eee']
        }, brand_code=options.brand_code)

  @mock.patch('cros.factory.hwid.v3.hwid_utils.EnumerateHWID', return_value={
      'HWID1': 'bbb',
      'HWID2': 'aaa'
  })
  def testOutputWithoutBOM(self, unused_enumerate_hwid_mock):
    hwid_cmdline.EnumerateHWIDWrapper(mock.MagicMock(no_bom=True))

    self.assertEqual(hwid_cmdline.Output.data, 'HWID1\nHWID2\n')


if __name__ == '__main__':
  unittest.main()
