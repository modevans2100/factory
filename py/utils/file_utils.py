# Copyright 2012 The Chromium OS Authors. All rights reserved.
"""File-related utilities."""
import contextlib
import threading
import time
import zipimport

from . import platform_utils
from . import process_utils
from . import type_utils

# Block size in bytes for iteratively generating hashes of files.
_HASH_FILE_READ_BLOCK_SIZE = 1024 * 64  # 64kb
def MakeDirsUidGid(path, uid=-1, gid=-1, mode=0o777):
      raise TypeError('Unexpected exclude type %s' % type(exclude))
    type_utils.CheckDictKeys(value, ['include', 'exclude'])
def CreateTemporaryFile(**kwargs):
  """Gets an unopened temporary file.

  This is similar to UnopenedTemporaryFile except that CreateTemporaryFile is
  not a context manager and will not try to delete the allocated file, making it
  more convenient for unittest style programs to get temporary files in setUp
  and delete on tearDown.

  In comparison to tempfile.mkstemp, this function does not return an opened fd,
  thus avoiding potential file handle leaks.

  Args:
    Any allowable arguments to tempfile.NamedTemporaryFile (e.g., prefix,
      suffix, dir) except 'delete'.

  Returns:
    A file path.
  """
  assert kwargs.get('delete') is not True, 'CreateTemporaryFile never deletes.'
  kwargs['delete'] = False
  with tempfile.NamedTemporaryFile(**kwargs) as f:
    path = f.name
  return path


@contextlib.contextmanager
    Any allowable arguments to tempfile.NamedTemporaryFile (e.g., prefix,
  path = CreateTemporaryFile(**kwargs)
@contextlib.contextmanager
      return dut.ReadSpecialFile(filename).splitlines(True)
    original = ReadFile(path)
  process_utils.Spawn(['sync'], log=log, check_call=True)
def IsGzippedFile(path):
  """Check if the given file is gzipped. (Not 100% accurate)

  Args:
    path: path to the file to check.

  Returns:
    True if it looks like a gzipped file.
  """
  with open(path, 'rb') as f:
    return f.read(2) == '\x1f\x8b'


@contextlib.contextmanager
    output_path = CreateTemporaryFile(prefix='GunzipSingleFile_')
def GetCompressor(file_format, allow_parallel=True):
  """Returns a compressor program for given file format.

  Args:
    file_format: A string for compression format (bz2, gz, xz).
    allow_parallel: True to return best compressor in multi-thread.

  Returns:
    A string for compressor program name, or None if nothing found.
  """
  program_map = {
      'gz': ['pigz', 'gzip'],
      'bz2': ['lbzip2', 'pbzip2', 'bzip2'],
      'xz': ['pixz', 'xz'],
  }
  program_list = program_map[file_format]
  if not allow_parallel:
    program_list = program_list[-1:]
  for program in program_list:
    if os.system('type %s >/dev/null 2>&1' % program) == 0:
      return program
  return None


                overwrite=True, quiet=False, use_parallel=False,
                exclude=None):
    use_parallel: Allow using parallel compressor to shorten execution time.
    exclude: a list of file patterns to exclude.

  only_extracts = type_utils.MakeList(only_extracts) if only_extracts else []
    exclude_opt = ['-x'] + exclude if exclude else []
           only_extracts + exclude_opt)
    formats = (
        (['.tar'], None),
        (['.tar.gz', '.tgz'], 'gz'),
        (['.tar.bz2', '.tbz2'], 'bz2'),
        (['.tar.xz', '.txz'], 'xz'))
    unsupported = True
    for suffixes, file_format in formats:
      if any(compressed_file.endswith(suffix) for suffix in suffixes):
        unsupported = False
        cmd = ['tar', '-xf', compressed_file, '-C', output_dir]
        if not overwrite:
          cmd += ['--keep-old-files']
        if not quiet:
          cmd += ['-vv']
        if use_parallel:
          cmd += ['-I', GetCompressor(file_format, use_parallel)]
        if exclude:
          cmd += ['--exclude=%s' % e for e in exclude]
        cmd += only_extracts
        break
    if unsupported:
      raise ExtractFileError('Unsupported compressed file: %s' %
                             compressed_file)
  return process_utils.Spawn(cmd, log=True, check_call=True)
    path: path to check.
def AtomicCopy(source, dest, mode=None):
    source: source filename.
    dest: destination filename.
    mode: new file mode if specified.
  with UnopenedTemporaryFile(prefix='atomic_copy_') as temp_path:
    if mode is not None:
      os.chmod(temp_path, mode)
def FileHash(path, algorithm, block_size=_HASH_FILE_READ_BLOCK_SIZE):
  """Calculates given hash of a local file.
  From: http://stackoverflow.com/questions/1742866/compute-crc-of-file-in-python
  Args:
    path: Local path of the file.
    algorithm: Name of algorithm to use.  Should be one of algorithms available
               in hashlib.algorithms.  For example: md5, sha1

  Returns:
    Hashlib object representing the given file.
  """
  file_hash = hashlib.new(algorithm)
  with open(path, 'rb') as f:
    for chunk in iter(lambda: f.read(block_size), ''):
      file_hash.update(chunk)
  return file_hash


def MD5InHex(path):
  """Returns hex-encoded MD5 sum of given file."""
  return FileHash(path, 'md5').hexdigest()


def MD5InBase64(path):
  """Returns base64-encoded MD5 sum of given file."""
  return base64.standard_b64encode(FileHash(path, 'md5').digest())


def SHA1InHex(path):
  """Returns hex-encoded SHA1 sum of given file."""
  return FileHash(path, 'sha1').hexdigest()


def SHA1InBase64(path):
  """Returns base64-encoded SHA1 sum of given file."""
  return base64.standard_b64encode(FileHash(path, 'sha1').digest())


# Legacy function names for backwards compatibility.
# TODO(kitching): Remove these functions after M56 stable release.
Md5sumInHex = MD5InHex
B64Sha1 = SHA1InBase64
    retry_secs: seconds to wait between retries when timeout_secs is not None.
  def __init__(self, lockfile, timeout_secs=None, retry_secs=0.1):
    self._retry_secs = retry_secs
    self._fd = None
    self._fd = os.open(self._lockfile, os.O_RDWR | os.O_CREAT)
    remaining_secs = self._timeout_secs
        logging.debug('%s (%d) locked by %s',
                      self._lockfile, self._fd, os.getpid())
        if self._timeout_secs is not None:
          # We don't want to use real system time because the sleep may
          # be longer due to system busy or suspend/resume.
          time.sleep(self._retry_secs)
          remaining_secs -= self._retry_secs
          if remaining_secs < 0:
      logging.debug('%s (%d) unlocked by %s',
                    self._lockfile, self._fd, os.getpid())
    if self._fd:
      os.close(self._fd)
      self._fd = None
  process = process_utils.Spawn(
    raise RuntimeError('Unable to write %s' % file_path)
    raise ValueError('Expected one match for %s but got %s' %
                     (pattern, matches))
def LoadModuleResource(path):
  """Loads a file that lives in same place with python modules.

  This is very similar to ReadFile except that the path can be a real file or
  virtual path inside Python ZIP (PAR).

  Args:
      path: The path to the file.

  Returns:
      Contents of resource in path, or None if the resource cannot be found.
  """
  if os.path.exists(path):
    return ReadFile(path)

  try:
    file_dir = os.path.dirname(path)
    file_name = os.path.basename(path)
    importer = zipimport.zipimporter(file_dir)
    zip_path = os.path.join(importer.prefix, file_name)
    return importer.get_data(zip_path)
  except Exception:
    pass

  return None




def HashPythonArchive(par_path):
  hashes = HashFiles(
      os.path.dirname(par_path),
      lambda path: path == par_path,
      # Use first 4 bytes of SHA1
      hash_function=lambda data: hashlib.sha1(data).hexdigest()[0:8])
  if not hashes:
    raise RuntimeError('No sources found at %s' % par_path)

  return dict(
      # Log hash function used, just in case we ever want to change it
      hash_function=SOURCE_HASH_FUNCTION_NAME,
      hashes=hashes)


class FileLockContextManager(object):
  """Represents a file lock in context manager's form

  Provides two different levels of lock around the associated file.
  - For accessing a file in the same process, please make sure all the access
  goes through this class, the internal lock will guarantee no racing with that
  file.
  - For accessing a file across different process, this class will put an
  exclusive advisory lock during "with" statement.

  Args:
    path: Path to the file.
    mode: Mode used to open the file.
  """

  def __init__(self, path, mode):
    self.path = path
    self.mode = mode
    self.opened = False
    self.file = None
    self._lock = threading.Lock()
    self._filelock = platform_utils.GetProvider('FileLock')

  def __enter__(self):
    """Locks the associated file."""
    self._lock.acquire()
    self._OpenUnlocked()
    self._filelock(self.file.fileno(), True)
    return self.file

  def __exit__(self, ex_type, value, tb):
    """Unlocks the associated file."""
    del ex_type, value, tb
    self._filelock(self.file.fileno(), False)
    self._lock.release()

  def Close(self):
    """Closes associated file."""
    if self.file:
      with self._lock:
        self.opened = False
        self.file.close()
        self.file = None

  def _OpenUnlocked(self):
    parent_dir = os.path.dirname(self.path)
    if not os.path.exists(parent_dir):
      try:
        os.makedirs(parent_dir)
      except OSError:
        # Maybe someone else tried to create it simultaneously
        if not os.path.exists(parent_dir):
          raise

    if self.opened:
      return

    self.file = open(self.path, self.mode)
    self.opened = True


def SyncDirectory(dir_path):
  """Flush and sync directory on file system.

  Python 2.7 does not support os.sync() so this is the closest way to flush file
  system meta data changes.
  """
  try:
    dir_fd = os.open(dir_path, os.O_DIRECTORY)
    os.fsync(dir_fd)
  except Exception:
    logging.exception('Failed syncing in directory: %s', dir_path)
  finally:
    try:
      os.close(dir_fd)
    except Exception:
      pass


@contextlib.contextmanager
def AtomicWrite(path, binary=False, fsync=True):
  """Atomically writes to the given file.

  Uses write-rename strategy with fsync to atomically write to the given file.

  Args:
    binary: Whether or not to use binary mode in the open() call.
    fsync: Flushes and syncs data to disk after write if True.
  """
  # TODO(kitching): Add Windows support.  On Windows, os.rename cannot be
  #                 used as an atomic operation, since the rename fails when
  #                 the target already exists.  Additionally, Windows does not
  #                 support fsync on a directory as done below in the last
  #                 conditional clause.  Some resources suggest using Win32
  #                 API's MoveFileEx with MOVEFILE_REPLACE_EXISTING mode,
  #                 although this relies on filesystem support and won't work
  #                 with FAT32.
  mode = 'wb' if binary else 'w'
  path_dir = os.path.abspath(os.path.dirname(path))
  path_file = os.path.basename(path)
  assert path_file != ''  # Make sure path contains a file.
  with UnopenedTemporaryFile(prefix='%s_atomicwrite_' % path_file,
                             dir=path_dir) as tmp_path:
    with open(tmp_path, mode) as f:
      yield f
      if fsync:
        f.flush()
        os.fdatasync(f.fileno())
    # os.rename is an atomic operation as long as src and dst are on the
    # same filesystem.
    os.rename(tmp_path, path)
  if fsync:
    SyncDirectory(path_dir)


def SymlinkRelative(target, link_path, base=None, force=False):
  """Makes a relative symlink to target

  If base is not None, only make symlink relative if both link_path and target
  are under the absolute path given by base.

  If force is True, try to unlink link_path before doing symlink.

  If target is a relative path, it would be directly used as argument of
  os.symlink, and base argument is ignored.

  This function does not check the existence of target.

  Args:
    target: target file path.
    link_path: symlink path, can be absolute or relative to current dir.
    base: only make symlink relative if both target and link_path are under this
          path.
    force: whether to force symlink even if link_path exists.

  Raises:
    OSError: failed to make symlink
  """
  link_path = os.path.abspath(link_path)

  if os.path.isabs(target):
    if base is not None and base[-1] != '/':
      # Make sure base ends with a /
      base += '/'
    if base is None or os.path.commonprefix([base, target, link_path]) == base:
      target = os.path.relpath(target, os.path.dirname(link_path))

  if force:
    TryUnlink(link_path)

  os.symlink(target, link_path)