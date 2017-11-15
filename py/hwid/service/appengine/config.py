# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Cloud stoarge buckets and service environment configuration."""

import os

import factory_common  # pylint: disable=unused-import
from cros.factory.hwid.service.appengine import filesystem_adapter
from cros.factory.hwid.service.appengine import hwid_manager


_CONFIGURATIONS = {
    's~google.com:chromeoshwid': {
        'env': 'prod',
        'bucket': 'chromeoshwid',
        'ge_bucket': 'chromeos-build-release-console',
    },
    's~google.com:chromeoshwid-staging': {
        'env': 'staging',
        'bucket': 'chromeoshwid-staging',
        'ge_bucket': 'chromeos-build-release-console-staging',
    },
    'default': {
        'env': 'dev',
        'bucket': 'chromeoshwid-dev',
        # Allow unauthenticated access when running a local dev server and
        # during tests.
        'skip_auth_check': True,
        'ge_bucket': 'chromeos-build-release-console-staging',
    }
}


class _Config(object):
  """Config for AppEngine environment.

  Attributes:
    env: A string for the environment.
    skip_auth_check: A bool for skipping authentic check.
    goldeneye_filesystem: A FileSystemAdapter object, the GoldenEye filesystem
        on CloudStorage.
    hwid_filesystem: A FileSystemAdapter object, the HWID filesystem on
        CloudStorage.
    hwid_manager: A HwidManager object. HwidManager manipulates HWIDs in
        hwid_filesystem.
  """

  def __init__(self):
    super(_Config, self).__init__()
    try:
      app_id = os.environ['APPLICATION_ID']
      conf = _CONFIGURATIONS.get(app_id, _CONFIGURATIONS['default'])
    except KeyError:
      conf = _CONFIGURATIONS['default']

    self.env = conf['env']
    self.skip_auth_check = conf.get('skip_auth_check', False)
    self.goldeneye_filesystem = filesystem_adapter.CloudStorageAdapter(
        conf['ge_bucket'])
    self.hwid_filesystem = filesystem_adapter.CloudStorageAdapter(
        conf['bucket'])
    self.hwid_manager = hwid_manager.HwidManager(self.hwid_filesystem)


CONFIG = _Config()