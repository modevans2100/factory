# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# pylint: disable=E1101

"""Umpire resource map web application.

The class handles http://umpire_address:umpire_port/resourcemap' HTTP GET.
"""

import logging

import factory_common  # pylint: disable=W0611
from cros.factory.umpire.bundle_selector import ParseDUTHeader, GetResourceMap
from cros.factory.umpire.web.wsgi import WSGISession


_PATH_INFO = '/resourcemap'


class ResourceMapApp(object):

  """Web application callable class.

  Args:
    env: UmpireEnv object.
  """

  def __init__(self, env):
    self.env = env

  def __call__(self, environ, start_response):
    """Gets resource map from DUT info and return text/plain result."""
    session = WSGISession(environ, start_response)
    logging.debug('resourcemap app: %s', str(session))
    if session.REQUEST_METHOD == 'GET':
      dut_info = ParseDUTHeader(session.HTTP_X_UMPIRE_DUT)
      return session.Respond(GetResourceMap(dut_info, self.env))
    return session.BadRequest400()

  def GetPathInfo(self):
    return _PATH_INFO