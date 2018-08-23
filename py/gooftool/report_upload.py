# Copyright 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""gft_upload: Provides various protocols for uploading report files.
"""

import ftplib
import logging
import os
import re
import sys
import time
import urllib
import urlparse
import xmlrpclib

import factory_common  # pylint: disable=unused-import
from cros.factory.gooftool.common import Shell
from cros.factory.utils import file_utils
from cros.factory.utils.type_utils import Error


# Constants
DEFAULT_MAX_RETRY_TIMES = 0
DEFAULT_RETRY_INTERVAL = 60
DEFAULT_RETRY_TIMEOUT = 30


def RetryCommand(callback, message_prefix, max_retry_times, interval):
  """Retries running some commands until success or fail `max_retry_times`
     times.

  Args:
    callback: A callback function to execute specified command, and return
              if the result is success. Callback accepts a param to hold session
              states, including two special values:
                'message' to be logged, and 'abort' to return immediately.
    message_prefix: Prefix string to be displayed.
    max_retry_times: Number of tries before raising an error (0 to retry
                     infinitely).
    interval: Duration (in seconds) between each retry.

  Returns:
    raises Error when the command fails `max_retry_times` times or aborted.
  """
  results = {}
  tries = 0
  # Currently we do endless retry, if interval is assigned.
  while not callback(results):
    message = results.get('message', 'unknown')
    abort = results.get('abort', False)
    logging.error('%s: %s', message_prefix, message)
    if abort:
      raise Error('Aborted.')
    if max_retry_times:
      tries += 1
      logging.info('Failed %d times. %d tries left.',
                   tries, max_retry_times - tries)
      if tries == max_retry_times:
        raise Error('Max number of tries reached.')

    for i in range(interval, 0, -1):
      if i % 10 == 0:
        sys.stderr.write(' Retry in %d seconds...\n' % i)
      time.sleep(1)


def ShopFloorUpload(source_path, remote_spec, stage,
                    max_retry_times=DEFAULT_MAX_RETRY_TIMES,
                    retry_interval=DEFAULT_RETRY_INTERVAL):
  if '#' not in remote_spec:
    raise Error('ShopFloorUpload: need a valid parameter in URL#SN format.')
  (server_url, _, serial_number) = remote_spec.partition('#')
  logging.debug('ShopFloorUpload: [%s].UploadReport(%s, %s)',
                server_url, serial_number, source_path)
  instance = xmlrpclib.ServerProxy(server_url, allow_none=True, verbose=False)
  blob = xmlrpclib.Binary(file_utils.ReadFile(source_path))
  cmd_result = Shell('mosys platform model')
  model = ''
  if cmd_result.status == 0:
    model = cmd_result.stdout.strip()
  option_name = model + '-gooftool' if model else 'gooftool'

  def ShopFloorCallback(result):
    try:
      instance.UploadReport(serial_number, blob, option_name, stage)
      return True
    except xmlrpclib.Fault as err:
      result['message'] = 'Remote server fault #%d: %s' % (err.faultCode,
                                                           err.faultString)
      result['abort'] = True
    except Exception:
      result['message'] = sys.exc_info()[1]
      result['abort'] = False

  RetryCommand(ShopFloorCallback, 'ShopFloorUpload',
               max_retry_times=max_retry_times, interval=retry_interval)
  logging.info('ShopFloorUpload: successfully uploaded to: %s', remote_spec)


def CurlCommand(curl_command, success_string=None, abort_string=None,
                max_retry_times=DEFAULT_MAX_RETRY_TIMES,
                retry_interval=DEFAULT_RETRY_INTERVAL):
  """Performs arbitrary curl command with retrying.

  Args:
    curl_command: Parameters to be invoked with curl.
    success_string: String to be recognized as "uploaded successfully".
        For example: '226 Transfer complete'.
    abort_string: String to be recognized to abort retrying.
    max_retry_times: Number of tries to execute the command (0 to retry
                     infinitely).
    retry_interval: Duration (in seconds) between each retry.
  """
  if not curl_command:
    raise Error('CurlCommand: need parameters for curl.')

  # If we want to match success_string in output, we should enable -v/--verbose,
  # otherwise, we can use -s/--silent.
  # -S/--show-error will make curl show errors when they occur.
  # If we want to match success_string or abort_string,
  # we should redirect stderr to stdout and match in stdout to get all the
  # output by curl.
  # You may need to use -k/--insecure to allow connections to SSL sites
  # without certificate.

  arg_verbose_silent = '-v' if success_string else '-s'
  arg_redirect_stderr = '--stderr -' if success_string or abort_string else ''
  cmd = 'curl -S %s %s %s' % (arg_verbose_silent, arg_redirect_stderr,
                              curl_command)
  logging.debug('CurlCommand: %s', cmd)

  # man curl(1) for EXIT CODES not related to temporary network failure.
  curl_abort_exit_codes = [1, 2, 3, 27, 37, 43, 45, 53, 54, 58, 59, 63]

  def CurlCallback(result):
    cmd_result = Shell(cmd)
    abort = False
    message = None
    return_value = False
    if abort_string and cmd_result.stdout.find(abort_string) >= 0:
      message = 'Abort: Found abort pattern: %s' % abort_string
      abort = True
      return_value = False
    elif cmd_result.success:
      if success_string and cmd_result.stdout.find(success_string) < 0:
        message = 'Retry: No valid pattern (%s) in response.' % success_string
      else:
        return_value = True
    else:
      message = '#%d %s' % (cmd_result.status, cmd_result.stderr
                            if cmd_result.stderr else cmd_result.stdout)
      if cmd_result.status in curl_abort_exit_codes:
        abort = True

    logging.debug('CurlCallback: original response: %s',
                  ' '.join(cmd_result.stdout.splitlines()))
    result['abort'] = abort
    result['message'] = message
    return return_value

  RetryCommand(CurlCallback, 'CurlCommand',
               max_retry_times=max_retry_times, interval=retry_interval)
  logging.info('CurlCommand: successfully executed: %s', cmd)


def CurlUrlUpload(source_path, params, **kargs):
  """Uploads the source file with URL-like protocols by curl.

  Args:
    source_path: File to upload.
    params: Parameters to be invoked with curl.
    max_retry_times: Number of tries to upload (0 to retry infinitely).
    retry_interval: Duration (in seconds) between each retry.
  """
  return CurlCommand('--ftp-ssl -T "%s" %s' % (source_path, params), **kargs)


def CpfeUpload(source_path, cpfe_url, **kargs):
  """Uploads the source file to ChromeOS Partner Front End site.

  Args:
    source_path: File to upload.
    cpfe_url: URL to CPFE.
    max_retry_times: Number of tries to upload (0 to retry infinitely).
    retry_interval: Duration (in seconds) between each retry.
  """
  curl_command = '--form "report_file=@%s" %s' % (source_path, cpfe_url)
  CPFE_SUCCESS = 'CPFE upload: OK'
  CPFE_ABORT = 'CPFE upload: Failed'
  return CurlCommand(curl_command, success_string=CPFE_SUCCESS,
                     abort_string=CPFE_ABORT, **kargs)


def FtpUpload(source_path, ftp_url,
              max_retry_times=DEFAULT_MAX_RETRY_TIMES,
              retry_interval=DEFAULT_RETRY_INTERVAL,
              retry_timeout=DEFAULT_RETRY_TIMEOUT):
  """Uploads the source file to a FTP url.

    source_path: File to upload.
    ftp_url: A ftp url in ftp://user@pass:host:port/path format.
    max_retry_times: Number of tries to upload (0 to retry infinitely).
    retry_interval: Duration (in seconds) between each retry.
    retry_timeout: Connection timeout (in seconds).

  Raises:
    GFTError: When input url is invalid, or if network issue without retry.
  """
  # scheme: ftp, netloc: user:pass@host:port, path: /...
  url_struct = urlparse.urlparse(ftp_url)
  regexp = '(([^:]*)(:([^@]*))?@)?([^:]*)(:(.*))?'
  tokens = re.match(regexp, url_struct.netloc)
  userid = tokens.group(2)
  passwd = tokens.group(4)
  host = tokens.group(5)
  port = tokens.group(7)

  # Check and specify default parameters
  if not host:
    raise Error('FtpUpload: invalid ftp url: %s' % ftp_url)
  if not port:
    port = ftplib.FTP_PORT
  if not userid:
    userid = 'anonymous'
  if not passwd:
    passwd = ''

  # Parse destination path: According to RFC1738, 3.2.2,
  # Starting with %2F means absolute path, otherwise relative.
  path = urllib.unquote(url_struct.path)
  assert path[0] == '/', 'Unknown FTP URL path.'
  path = path[1:]

  source_name = os.path.split(source_path)[1]
  dest_name = os.path.split(path)[1]
  logging.debug('source name: %s, dest_name: %s -> %s',
                source_name, path, dest_name)
  if source_name and (not dest_name):
    path = os.path.join(path, source_name)

  ftp = ftplib.FTP()
  url = 'ftp://%s:%s@%s:%s/ %s' % (userid, passwd, host, port, path)
  logging.info('FtpUpload: target is %s', url)

  def FtpCallback(result):
    try:
      ftp.connect(host=host, port=port, timeout=retry_timeout)
    except Exception as e:
      result['message'] = '%s' % e
      return False
    return True

  RetryCommand(FtpCallback, 'FtpUpload',
               max_retry_times=max_retry_times, interval=retry_interval)

  # Ready for copying files
  logging.debug('FtpUpload: connected, uploading to %s...', path)
  ftp.login(user=userid, passwd=passwd)
  with open(source_path, 'rb') as fileobj:
    ftp.storbinary('STOR %s' % path, fileobj)
  logging.debug('FtpUpload: upload complete.')
  ftp.quit()
  logging.info('FtpUpload: successfully uploaded to %s', ftp_url)
