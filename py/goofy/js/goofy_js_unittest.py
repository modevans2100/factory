#!/usr/bin/python
#
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""The unittest that use closure compiler to catch common error in goofy.js."""

import os
import subprocess
import unittest


SCRIPT_DIR = os.path.dirname(__file__)


class GoofyJSTest(unittest.TestCase):
  def runTest(self):
    static_dir = os.path.join(SCRIPT_DIR, '..', 'static')
    subprocess.check_call(['make', '-C', static_dir, 'check_js'])


if __name__ == '__main__':
  unittest.main()
