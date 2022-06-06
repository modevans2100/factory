# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import logging
import textwrap
from typing import List
import urllib.error
import urllib.request

import google.auth
import google.auth.transport.requests


class HWIDAPIRequestException(Exception):
  """An Exception raised when fail to request HWID API."""


class HWIDAPIConnector:
  """Connector for accessing HWID API server."""

  _HWID_API_SCOPE = 'https://www.googleapis.com/auth/chromeoshwid'
  _GERRIT_URL = 'https://chrome-internal-review.googlesource.com'
  _GERRIT_HWID_URI = _GERRIT_URL + '/c/chromeos/chromeos-hwid/+/%(clNumber)s'

  def __init__(self, hwid_api_endpoint: str):
    """Initializes a HWID API client by the given HWID API endpoint.

    Args:
      hwid_api_endpoint: A string of the HWID API endpoint.
    """
    self._logger = logging.getLogger('HWIDAPIConnector')
    self._hwid_api_endpoint = hwid_api_endpoint

  def CreateHWIDFirmwareInfoCL(self, bundle_record: str,
                               original_requester: str) -> List[str]:
    """Sends HTTP request to HWID API to create HWID firmware info change.

    Args:
      bundle_record: A JSON string which created by finalize_bundle.
      original_requester: The email of original_requester from
          EasyBundleCreation.

    Returns:
      A list contains created HWID CL url.

    Raises:
      HWIDAPIRequestException: If it fails to call the HWID API.
    """
    token = self._GetAuthToken()
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    # TODO(b/232487900): Make `data` supports the field `bug_number`.
    data = {
        'original_requester':
            original_requester,
        'description':
            textwrap.dedent("""\
            This CL is created by EasyBundleCreation service.

            Please DO NOT submit this to CQ manually. It will be auto merged
            without approval.
            """),
        'bundle_record':
            bundle_record
    }
    data = json.dumps(data).encode()

    url = self._hwid_api_endpoint + '/v2/createHwidDbFirmwareInfoUpdateCl'
    request = urllib.request.Request(url, headers=headers, method='POST',
                                     data=data)

    self._logger.info('Request HTTP POST to %s', url)
    try:
      with urllib.request.urlopen(request) as r:
        response = json.load(r)
    except urllib.error.HTTPError as ex:
      error_msg = ex.read()
      try:
        error_msg = json.dumps(json.loads(error_msg), indent=2)
      except json.decoder.JSONDecodeError:
        pass
      raise HWIDAPIRequestException(error_msg)

    self._logger.info('Response: %s', response)

    cl_url = []
    if 'commits' in response:
      for commit in response['commits'].values():
        cl_url.append(self._GERRIT_HWID_URI % commit)

    return cl_url

  def _GetAuthToken(self) -> str:
    """Gets the authorization token to access HWID API.

    Returns:
      A token string can be used by HTTP request.
    """
    credential, _ = google.auth.default(scopes=[self._HWID_API_SCOPE])
    credential.refresh(google.auth.transport.requests.Request())
    return credential.token