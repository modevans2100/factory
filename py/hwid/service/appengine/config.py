# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Cloud stoarge buckets and service environment configuration."""

import collections
import os

import yaml

# pylint: disable=import-error
from cros.factory.hwid.service.appengine import cloudstorage_adapter
from cros.factory.hwid.service.appengine import hwid_manager
from cros.factory.utils import file_utils
from cros.factory.utils import type_utils


_DEFAULT_CONFIGURATION = {
    'env': 'dev',
    'bucket': 'chromeoshwid-dev',
    # Allow unauthenticated access when running a local dev server and
    # during tests.
    'ge_bucket': 'chromeos-build-release-console-staging',
    'vpg_targets': {
        'SARIEN': {  # for unittests
            'board': 'sarien',
            'waived_comp_categories': ['ethernet']
        }
    },
    'dryrun_upload': True,
    'hw_checker_mail': 'noreply@google.com',
}

_RESOURCE_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', '..', '..', '..', '..',
    'resource')

_PATH_TO_APP_CONFIGURATIONS_FILE = os.path.join(_RESOURCE_DIR,
                                                'configurations.yaml')


_VerificationPayloadGenerationTargetInfo = collections.namedtuple(
    '_VerificationPayloadGenerationTargetInfo',
    ['board', 'waived_comp_categories'])


class _Config:
  """Config for AppEngine environment.

  Attributes:
    env: A string for the environment.
    goldeneye_filesystem: A FileSystemAdapter object, the GoldenEye filesystem
        on CloudStorage.
    hwid_filesystem: A FileSystemAdapter object, the HWID filesystem on
        CloudStorage.
    hwid_manager: A HwidManager object. HwidManager manipulates HWIDs in
        hwid_filesystem.
  """

  def __init__(self):
    super(_Config, self).__init__()
    self.cloud_project = os.environ.get('GOOGLE_CLOUD_PROJECT')
    self.gae_env = os.environ.get('GAE_ENV')
    try:
      confs = yaml.load(file_utils.ReadFile(_PATH_TO_APP_CONFIGURATIONS_FILE))
      conf = confs[self.cloud_project]
    except (KeyError, OSError, IOError):
      conf = _DEFAULT_CONFIGURATION

    self.env = conf['env']
    self.goldeneye_filesystem = cloudstorage_adapter.CloudStorageAdapter(
        conf['ge_bucket'])
    self.hwid_filesystem = cloudstorage_adapter.CloudStorageAdapter(
        conf['bucket'])
    self.hw_checker_mail = conf.get('hw_checker_mail', '')
    self.vpg_targets = {
        k: _VerificationPayloadGenerationTargetInfo(
            v['board'], v.get('waived_comp_categories', []))
        for k, v in conf.get('vpg_targets', {}).items()}
    self.hwid_manager = hwid_manager.HwidManager(self.hwid_filesystem,
                                                 self.vpg_targets)
    self.dryrun_upload = conf.get('dryrun_upload', False)
    self.ingestion_api_key = conf.get('ingestion_api_key', None)
    self.project_region = conf.get('project_region', '')
    self.queue_name = conf.get('queue_name', '')
    self.hwid_repo_branch = conf.get('hwid_repo_branch', '')
    self.client_allowlist = conf.get('client_allowlist', [])


CONFIG = type_utils.LazyObject(_Config)
