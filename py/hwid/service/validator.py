# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Validator for HWID configs."""

import logging

import factory_common # pylint: disable=unused-import
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import verify_db_pattern


class ValidationError(ValueError):
  """Indicates that validation of the HWID config failed."""
  pass


def Validate(hwid_config_contents):
  """Validates a HWID config.

  Uses strict validation (i.e. includes checksum validation).

  Args:
    hwid_config_contents: the HWID config in unicode.
  """
  expected_checksum = database.Database.ChecksumForText(
      hwid_config_contents.encode("utf8")).decode("utf8")

  try:
    # Validate config by loading it.
    database.Database.LoadData(
        hwid_config_contents, expected_checksum=expected_checksum)
    return
  except common.HWIDException as e:
    raise ValidationError(e.message)


def ValidateChange(new_hwid_config, old_hwid_config):
  """Validates a HWID config change.

  This method validates the new config (strict, i.e. including its
  checksum), the old config (non strict, i.e. no checksum validation)
  and the change itself (e.g. bitfields may only be appended at the end, not
  inserted in the middle).

  Args:
    new_hwid_config: the new HWID config in unicode.
    old_hwid_config: the old HWID config in unicode (w/o checksum).
  """
  try:
    old_db = database.Database.LoadData(
        old_hwid_config, expected_checksum=None)
  except common.HWIDException as e:
    logging.exception("Previous version not valid: %r", e.message)
    raise ValidationError("Previous version of HWID config is not valid.")

  expected_checksum = database.Database.ChecksumForText(
      new_hwid_config.encode("utf8")).decode("utf8")

  try:
    # Load and validate current config.
    db = database.Database.LoadData(
        new_hwid_config, expected_checksum=expected_checksum)
    # Verify that the change is valid.
    verify_db_pattern.HWIDDBsPatternTest.VerifyParsedDatabasePattern(
        old_db, db)
  except common.HWIDException as e:
    raise ValidationError(e.message)