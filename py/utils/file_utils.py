# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
"""File-related utilities..."""
from contextlib import contextmanager
import tempfile
import factory_common  # pylint: disable=W0611
from cros.factory.utils import platform_utils
from cros.factory.utils import time_utils
from cros.factory.utils.process_utils import Spawn
from cros.factory.utils.type_utils import CheckDictKeys
from cros.factory.utils.type_utils import MakeList
def MakeDirsUidGid(path, uid=-1, gid=-1, mode=0777):
      raise TypeError, 'Unexpected exclude type %s' % type(exclude)
    CheckDictKeys(value, ['include', 'exclude'])
@contextmanager
    Any allowable arguments to tempfile.mkstemp (e.g., prefix,
  f, path = tempfile.mkstemp(**kwargs)
  os.close(f)
@contextmanager
def Read(filename):
  """Returns the content of a file.

  It is used to facilitate unittest.

  Args:
    filename: file name.

  Returns:
    File content. None if IOError.
  """
  try:
    with open(filename) as f:
      return f.read()
  except IOError as e:
    logging.error('Cannot read file "%s": %s', filename, e)
    return None


      return dut.ReadFile(filename, skip=0).splitlines(True)
    original = Read(path)
  Spawn(['sync'], log=log, check_call=True)
@contextmanager
    f, output_path = tempfile.mkstemp()
    os.close(f)
                overwrite=True, quiet=False):
  only_extracts = MakeList(only_extracts) if only_extracts else []
           only_extracts)
  elif (any(compressed_file.endswith(suffix) for suffix in
            ('.tar.bz2', '.tbz2', '.tar.gz', '.tgz', 'tar.xz', '.txz'))):
    overwrite_opt = [] if overwrite else ['--keep-old-files']
    verbose_opt = [] if quiet else ['-vv']
    cmd = (['tar', '-xf'] +
           overwrite_opt + [compressed_file] + verbose_opt +
           ['-C', output_dir] + only_extracts)
    raise ExtractFileError('Unsupported compressed file: %s' % compressed_file)
  return Spawn(cmd, log=True, check_call=True)
    path: path to check
def AtomicCopy(source, dest):
    source: source filename
    dest: destination filename
  with UnopenedTemporaryFile() as temp_path:
def Md5sumInHex(filename):
  """Gets hex coded md5sum of input file."""
  # pylint: disable=E1101
  return hashlib.md5(
      open(filename, 'rb').read()).hexdigest()
def B64Sha1(filename):
  """Gets standard base64 coded sha1 sum of input file."""
  # pylint: disable=E1101
  return base64.standard_b64encode(hashlib.sha1(
      open(filename, 'rb').read()).digest())
  def __init__(self, lockfile, timeout_secs=None):
    self._fd = os.open(lockfile, os.O_RDWR | os.O_CREAT)
    if self._timeout_secs:
      end_time = time_utils.MonotonicTime() + self._timeout_secs
        logging.debug('%s locked by %s', self._lockfile, os.getpid())
        if self._timeout_secs:
          time.sleep(0.1)
          if time_utils.MonotonicTime() > end_time:
      logging.debug('%s unlocked by %s', self._lockfile, os.getpid())
  process = Spawn(
    raise subprocess.CalledProcessError('Unable to write %s' % file_path)
    raise ValueError, 'Expected one match for %s but got %s' % (
        pattern, matches)