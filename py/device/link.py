# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TODO(hungte) Remove this legacy file when migration is over.

import factory_common  # pylint: disable=unused-import
from cros.factory.device import types

DeviceLink = types.DeviceLink

print('You have imported cros.factory.device.link, which is deprecated by '
      'cros.factory.device.types. Please migrate now.')