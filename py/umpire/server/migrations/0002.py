# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os


def Migrate():
  try:
    os.unlink('/var/db/factory/umpire/staging_umpire.yaml')
  except OSError:
    pass
