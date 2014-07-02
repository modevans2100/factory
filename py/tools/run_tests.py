#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runs unittests in parallel."""

import argparse
import logging
import os
import shutil
import signal
from subprocess import STDOUT
import sys
import tempfile
import time

import factory_common  # pylint: disable=W0611
from cros.factory import common
from cros.factory.utils import file_utils
from cros.factory.utils.process_utils import Spawn, CheckOutput

TEST_PASSED_MARK = '.tests-passed'
KILL_OLD_TESTS_TIMEOUT_SECS = 2
TEST_RUNNER_ENV_VAR = 'CROS_FACTORY_TEST_RUNNER'

def _MaybeRunPytestsOnly(tests, isolated_tests):
  """Filters tests according to changed file.

  If all modified files since last test run are inside py/test/pytests, we
  don't run unittests outside that directory.

  Args:
    tests: unittest paths.
    isolated_tests: isolated unittest paths.

  Returns:
    A tuple (filtered_tests, filtered_isolated_tests) containing filtered
    tests and isolated tests.
  """
  PYTEST_PATH = 'py/test/pytests'
  if not os.path.exists(TEST_PASSED_MARK):
    return (tests, isolated_tests)

  ls_tree = CheckOutput(['git', 'ls-tree', '-r', 'HEAD']).split('\n')
  files = [line.split()[3] for line in ls_tree if line]
  last_test_time = os.path.getmtime(TEST_PASSED_MARK)
  changed_files = [f for f in files if os.path.getmtime(f) > last_test_time]

  if not changed_files:
    # Nothing to test!
    return ([], [])

  if next((f for f in changed_files if not f.startswith(PYTEST_PATH)), None):
    return (tests, isolated_tests)

  return ([test for test in tests if test.startswith(PYTEST_PATH)],
          [test for test in isolated_tests if test.startswith(PYTEST_PATH)])

class _TestProc(object):
  """Creates and runs a subprocess to run an unittest.

  Besides creating a subprocess, it also prepares a temp directory for
  env CROS_FACTORY_ROOT, records a test start time and test path.

  The temp directory will be removed once the object is destroyed.

  Args:
    test_name: unittest path.
    log_name: path of log file for unittest.
  """
  def __init__(self, test_name, log_name):
    self.test_name = test_name
    self.log_file = open(log_name, 'w')
    self.start_time = time.time()
    self.cros_factory_root = tempfile.mkdtemp(prefix='cros_factory_root.')
    child_env = os.environ.copy()
    child_env['CROS_FACTORY_ROOT'] = self.cros_factory_root
    # Set TEST_RUNNER_ENV_VAR so we know to kill it later if
    # re-running tests.
    child_env[TEST_RUNNER_ENV_VAR] = os.path.basename(__file__)
    self.proc = Spawn(self.test_name, stdout=self.log_file, stderr=STDOUT,
                      env=child_env)
    self.pid = self.proc.pid
    self.returncode = None

  def __del__(self):
    if os.path.isdir(self.cros_factory_root):
      shutil.rmtree(self.cros_factory_root)


class RunTests(object):
  """Runs unittests in parallel.

  Args:
    tests: list of unittest paths.
    max_jobs: maxinum number of parallel tests to run.
    log_dir: base directory to store test logs.
    isolated_tests: list of test to run in isolate mode.
    fallback: True to re-run failed test sequentially.
  """
  def __init__(self, tests, max_jobs, log_dir, isolated_tests=None,
               fallback=True):
    self._tests = tests if tests else []
    self._max_jobs = max_jobs
    self._log_dir = log_dir
    self._isolated_tests = isolated_tests if isolated_tests else []
    self._fallback = fallback
    self._start_time = time.time()

    # A dict to store running subprocesses. pid: _TestProc.
    self._running_proc = {}

    self._passed_tests = set()  # set of passed test_name
    self._failed_tests = set()  # set of failed test_name

  def Run(self):
    """Runs all unittests.

    Returns:
      0 if all passed; otherwise, 1.
    """
    if self._max_jobs > 1:
      tests = set(self._tests) - set(self._isolated_tests)
      num_total_tests = len(tests) + len(self._isolated_tests)
      self._InfoMessage('Run %d tests in parallel with %d jobs:' %
                        (len(tests), self._max_jobs))
    else:
      tests = set(self._tests) | set(self._isolated_tests)
      num_total_tests = len(tests)
      self._InfoMessage('Run %d tests sequentially:' % len(tests))

    self._RunInParallel(tests, self._max_jobs)
    if self._max_jobs > 1 and self._isolated_tests:
      self._InfoMessage('Run %d isolated tests sequentially:' %
                        len(self._isolated_tests))
      self._RunInParallel(self._isolated_tests, 1)

    self._PassMessage('%d/%d tests passed.' % (len(self._passed_tests),
                                               num_total_tests))

    if self._failed_tests and self._fallback:
      self._InfoMessage('Re-run failed tests sequentially:')
      rerun_tests = list(self._failed_tests)
      self._failed_tests.clear()
      self._RunInParallel(rerun_tests, 1)
      self._PassMessage('%d/%d tests passed.' % (len(self._passed_tests),
                                                 len(self._tests)))

    self._InfoMessage('Elapsed time: %.2f s' % (time.time() - self._start_time))

    if self._failed_tests:
      self._FailMessage('Logs of %d failed tests:' % len(self._failed_tests))
      for test in self._failed_tests:
        self._FailMessage(self._GetLogFilename(test))
      return 1
    else:
      return 0

  def _GetLogFilename(self, test):
    """Composes log filename.

    Log filename is based on unittest path and we replace '/' with '_'.

    Args:
      test: unittest path.

    Returns:
      log filename (with path) for the test.
    """
    if test.find('./') == 0:
      test = test[2:]
    return os.path.join(self._log_dir, test.replace('/', '_') + '.log')

  def _RunInParallel(self, tests, max_jobs):
    """Runs tests in parallel.

    It creates subprocesses and runs in parallel for at most max_jobs.
    It is blocked until all tests are done.

    Args:
      tests: list of unittest paths.
      max_jobs: maximum number of tests to run in parallel.
    """
    for test_name in tests:
      try:
        p = _TestProc(test_name, self._GetLogFilename(test_name))
      except Exception as e:
        self._FailMessage('Error running test %r' % test_name)
        raise e
      self._running_proc[p.pid] = p
      self._WaitRunningProcessesFewerThan(max_jobs)
    # Wait for all running test.
    self._WaitRunningProcessesFewerThan(1)

  def _RecordTestResult(self, p):
    """Records test result.

    Places the completed test to either success or failure list based on
    its returncode. Also print out PASS/FAIL message with elapsed time.

    Args:
      p: _TestProc object.
    """
    duration = time.time() - p.start_time
    if p.returncode == 0:
      self._PassMessage('*** PASS [%.2f s] %s' % (duration, p.test_name))
      self._passed_tests.add(p.test_name)
    else:
      self._FailMessage('*** FAIL [%.2f s] %s (return:%d)' %
                        (duration, p.test_name, p.returncode))
      self._failed_tests.add(p.test_name)

  def _WaitRunningProcessesFewerThan(self, threshold):
    """Waits until #running processes is fewer than specifed.

    It is a blocking call. If #running processes >= thresold, it waits for a
    completion of a child.

    Args:
      threshold: if #running process is fewer than this, the call returns.
    """
    while len(self._running_proc) >= threshold:
      pid, status = os.wait()
      p = self._running_proc.pop(pid)
      p.returncode = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
      self._RecordTestResult(p)

  def _PassMessage(self, message):
    print '\033[22;32m%s\033[22;0m' % message

  def _FailMessage(self, message):
    print '\033[22;31m%s\033[22;0m' % message

  def _InfoMessage(self, message):
    print message


def KillOldTests():
  """Kills stale test processes.

  Looks for processes that have CROS_FACTORY_TEST_RUNNER=run_tests.py in
  their environment, mercilessly kills them, and waits for them
  to die.  If it can't kill all the processes within
  KILL_OLD_TESTS_TIMEOUT_SECS, returns anyway.
  """
  env_signature = '%s=%s' % (TEST_RUNNER_ENV_VAR, os.path.basename(__file__))

  pids_to_kill = []
  for pid in CheckOutput(['pgrep', '-U', os.environ['USER']]).splitlines():
    pid = int(pid)
    try:
      environ = file_utils.ReadFile('/proc/%d/environ' % pid)
    except IOError:
      # No worries, maybe the process already disappeared
      continue

    if env_signature in environ.split('\0'):
      pids_to_kill.append(pid)

  if not pids_to_kill:
    return

  logging.warning('Killing stale test processes %s', pids_to_kill)
  for pid in pids_to_kill:
    try:
      os.kill(pid, signal.SIGKILL)
    except OSError:
      if os.path.exists('/proc/%d' % pid):
        # It's still there.  We should have been able to kill it!
        logging.exception('Unable to kill stale test process %s', pid)

  start_time = time.time()
  while True:
    pids_to_kill = filter(lambda pid: os.path.exists('/proc/%d' % pid),
                          pids_to_kill)
    if not pids_to_kill:
      logging.warning('Killed all stale test processes')
      return

    if time.time() - start_time > KILL_OLD_TESTS_TIMEOUT_SECS:
      logging.warning('Unable to kill %s', pids_to_kill)
      return

    time.sleep(0.1)


def main():
  parser = argparse.ArgumentParser(description='Runs unittests in parallel.')
  parser.add_argument('--jobs', '-j', type=int, default=1,
                      help='Maximum number of tests to run in parallel.')
  parser.add_argument('--log', '-l', default='',
                      help='directory to place logs.')
  parser.add_argument('--isolated', '-i', nargs='*',
                      help='Isolated unittests which run sequentially.')
  parser.add_argument('--nofallback', action='store_true',
                      help='Do not re-run failed test sequentially.')
  parser.add_argument('--nofilter', action='store_true',
                      help='Do not filter tests.')
  parser.add_argument('--no-kill-old', action='store_false', dest='kill_old',
                      help='Do not kill old tests.')
  parser.add_argument('test', nargs='+', help='Unittest filename.')
  args = parser.parse_args()

  common.SetupLogging()

  test, isolated = ((args.test, args.isolated)
                    if args.nofilter
                    else _MaybeRunPytestsOnly(args.test, args.isolated))

  if os.path.exists(TEST_PASSED_MARK):
    os.remove(TEST_PASSED_MARK)

  if args.kill_old:
    KillOldTests()

  runner = RunTests(test, args.jobs, args.log,
                    isolated_tests=isolated, fallback=not args.nofallback)
  return_value = runner.Run()
  if return_value == 0:
    with open(TEST_PASSED_MARK, 'a'):
      os.utime(TEST_PASSED_MARK, None)
  sys.exit(return_value)

if __name__ == '__main__':
  main()
