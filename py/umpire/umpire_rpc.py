# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Umpire RPC base class."""


import factory_common  # pylint: disable=W0611


def RPCCall(method):
  """Enables the method to be Umpire RPC function.

  Args:
    method: an unbound derived UmpireRPC class method.

  Example:
    class Foo(UmpireRPC):
      def NonRPCFunction():
        pass

      @RPCCall
      def RPCFunction(parameter, ...):
        pass
  """
  method.is_rpc_method = True
  return method

class UmpireRPC(object):

  """RPC base class.

  Properties:
    env: UmpireEnv object.
  """
  def __init__(self, env):
    super(UmpireRPC, self).__init__()
    self.env = env

  @RPCCall
  def __nonzero__(self):
    """Truth value testing.

    It is used for handling request issued when client side performs truth
    value testing on RPC server proxy. For example:
      p = xmlrpclib.ServerProxy('http://127.0.0.1:9090')
      if p:  # <- this invokes __nonzero__() RPC call.
        p.DoSomething()

    Returns:
      True
    """
    return True
