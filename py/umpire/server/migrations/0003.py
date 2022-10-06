# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import hashlib
import json
import os

import yaml

# Private constants.
_ENV_DIR = '/var/db/factory/umpire'
_OLD_SYMLINK = os.path.join(_ENV_DIR, 'active_umpire.yaml')
_NEW_SYMLINK = os.path.join(_ENV_DIR, 'active_umpire.json')


def Migrate():
  with open(_OLD_SYMLINK, encoding='utf8') as f:
    json_config = json.dumps(
        yaml.safe_load(f), indent=2, separators=(',', ': '),
        sort_keys=True) + '\n'

    json_name = 'umpire.%s.json' % (
        hashlib.md5(json_config.encode('utf-8')).hexdigest())
  json_path = os.path.join('resources', json_name)
  with open(os.path.join(_ENV_DIR, json_path), 'w', encoding='utf8') as f:
    f.write(json_config)
  os.symlink(json_path, _NEW_SYMLINK)

  os.unlink(_OLD_SYMLINK)
