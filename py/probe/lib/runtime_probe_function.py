# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe.lib import probe_function
from cros.factory.probe.runtime_probe import runtime_probe_adapter


class RuntimeProbeFunction(probe_function.ProbeFunction):
  """The base class of runtime probe functions.

  While evaluation, the function proxies the argument to runtime probe and
  return its result. Override the following fields to indicate the function to
  call. See cros.factory.probe.runtime_probe.probe_config_definition for the
  possible values.
  """
  CATEGORY_NAME = None
  FUNCTION_NAME = None

  def Probe(self):
    if not self.CATEGORY_NAME or not self.FUNCTION_NAME:
      raise NotImplementedError
    return runtime_probe_adapter.RunProbeFunction(self.CATEGORY_NAME,
                                                  self.FUNCTION_NAME,
                                                  self.args.ToDict())
