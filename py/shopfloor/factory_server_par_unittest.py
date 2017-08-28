#!/usr/bin/env python

# Copyright 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Makes sure that shopfloor server can run in a standalone
environment (with only factory.par)."""

import logging
import os
import shutil
import tempfile
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.test.env import paths
from cros.factory.utils.process_utils import Spawn


class ShopFloorStandaloneTest(unittest.TestCase):

  def setUp(self):
    self.process = None
    self.tmp = tempfile.mkdtemp(prefix='shopfloor_standalone_unittest.')
    self.tmp_build_dir = tempfile.mkdtemp(
        prefix='shopfloor_standalone_unittest_build_dir.')

  def tearDown(self):
    if self.process and self.process.poll() is None:
      try:
        self.process.terminate()
      except Exception:
        pass
    shutil.rmtree(self.tmp)
    shutil.rmtree(self.tmp_build_dir)

  def runTest(self):
    script_dir = os.path.dirname(os.path.realpath(__file__))
    Spawn(['make', '-s', '-C', paths.FACTORY_DIR,
           'par', 'PAR_OUTPUT_DIR=%s' % self.tmp,
           'PAR_TEMP_DIR=%s' % self.tmp_build_dir],
          log=True, check_call=True)

    factory_server_path = os.path.join(self.tmp, 'factory_server')
    os.symlink(os.path.realpath(os.path.join(self.tmp, 'factory.par')),
               factory_server_path)

    os.environ['SHOPFLOOR_SERVER_CMD'] = factory_server_path
    # Disable all site directories to simulate a plain-vanilla Python.
    os.environ['CROS_SHOPFLOOR_PYTHON_OPTS'] = '-sS'

    server_unittest = os.path.join(script_dir, 'factory_server_unittest.py')
    self.process = Spawn([server_unittest], check_call=True, log=True)


if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO)
  unittest.main()
