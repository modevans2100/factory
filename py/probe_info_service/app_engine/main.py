# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import flask  # pylint: disable=import-error,no-name-in-module

from cros.factory.probe_info_service.app_engine import protorpc_utils
from cros.factory.probe_info_service.app_engine import stubby_handler


app = flask.Flask(__name__)

protorpc_utils.RegisterProtoRPCServiceToFlaskApp(
    app, '/_ah/stubby', stubby_handler.ProbeInfoService())
