#!/usr/bin/env python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for --verify_hwid_v2 command of gooftool."""

import logging
import os
import re
from tempfile import NamedTemporaryFile
import unittest
import yaml

import factory_common  # pylint: disable=W0611
from cros.factory.hwid.v2 import hwid_tool
from cros.factory.test.env import paths
from cros.factory.utils.process_utils import Spawn


def Indent(data):
  return re.sub('(?m)^', '    ', data)


class VerifyHWIDv2Test(unittest.TestCase):
  """Unit test for --verify_hwid_v2 command of gooftool."""

  def testHWIDRepo(self):
    hwid_dir = os.path.join(os.environ['CROS_WORKON_SRCROOT'],
                            'src', 'platform', 'chromeos-hwid', 'v2')
    if os.path.exists(hwid_dir):
      self._RunTest(hwid_dir)
    else:
      print 'testHWIDRepo: ignored, no %s in source tree.' % hwid_dir

  def testFakeData(self):
    self._RunTest(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'testdata'))

  def _RunTest(self, test_data_path):
    test_data = yaml.load_all(
        open(os.path.join(test_data_path, 'test_data.yaml')))

    failures = []
    for d in test_data:
      if not d:
        continue
      hwid = d.pop('HWID')
      try:
        expected_error = re.compile(d.pop('ERROR'))
      except KeyError:
        expected_error = None

      expected_verified = not expected_error

      with NamedTemporaryFile(
          prefix=(hwid.replace(' ', '_') + '.'), suffix='.yaml') as f:
        yaml.dump(d, f)
        f.flush()

        process = Spawn([os.path.join(paths.FACTORY_PATH, 'bin', 'gooftool'),
                         '--v=4',
                         'verify_hwid_v2',
                         '--hwid=%s' % hwid,
                         '--hwdb_path=%s' % test_data_path,
                         '--probe_results=%s' % f.name,
                         '--status'] +
                        list(hwid_tool.LIFE_CYCLE_STAGES),
                        log=True, call=True, read_stdout=True, read_stderr=True)

        verified = not process.returncode

        failure = None
        if expected_verified != verified:
          failure = 'expected_verified=%s, verified=%s' % (
              expected_verified, verified)
        elif (not expected_verified) and not expected_error.search(
            process.stderr_data):
          failure = 'expected regexp %r in stderr' % expected_error.pattern

        if failure:
          f.delete = False
          print '*** FAIL %s: %s\n  stdout:\n%s\n  stderr:\n%s\n' % (
              hwid, failure,
              Indent(process.stdout_data), Indent(process.stderr_data))
          failures.append(hwid)

    self.assertFalse(failures)


if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO)
  unittest.main()