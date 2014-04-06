#!/usr/bin/env python
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A long-lived tool that wraps raw logs into unified archives."""

# TODO(itspeter):
#   switch to cros.factory.hacked_argparse once migration to Umpire is fully
#   rolled-out.
import argparse
import copy
import logging
import os
import pprint
import re
import sys
import yaml


ALLOWED_DATA_TYPE = set(['eventlog', 'reports', 'regcode'])
ALLOWED_DURATION = {
    'hourly': 60*60,
    'daily': 60*60*24,
    'weekly': 60*60*24*7,
    'monthly': 60*60*24*7*30  # Assuming 30 days for a month.
}
ALLOWED_FORMAT = set(['.tar.xz', '.zip'])
DEFAULT_DURATION = ALLOWED_DURATION['daily']
DEFAULT_FORMAT = '.tar.xz'
DEFAULT_DELIMITER = {
  'eventlog': r'---\n',
  'regcode': r'\n'
}


class ArchiverFieldError(Exception):
  pass


class ArchiverConfig(object):
  """Necessary parameters for an indepedent cycle.

  Properties:
    source_dir: The directory for archiving.
    source_file: Same as source_dir. However, monitoring a single file instead
      of a directory, this is a legacy support for Umpire predecessor. One of
      source_dir or source_file must be existed at the time of an active cycle.
    archived_dir: The directory where archives will be stored.
    recycle_dir: The directory where we move archived data from source to
      recycle_dir. Data stored inside this directory means it is deletable at
      anytime.
    project: Board name, usually the software code name of a project.
      Additional phase is ecouraged to add (ex: EVT, DVT, MP). The string
      itself must meet regular expression [A-Za-z0-9_-].
    data_type: Name of the data_type. Will be appeared in the filename of
      generated archives. The string itself must meet regular expression
      [A-Za-z0-9_-].
    notes: Human readable annotation about current configuration.
    duration: Interval between active archiving cycle in seconds.
    delimiter: A multiline regular expression that help us to identify a
      complete chunk in a file.
    compress_format: Format of the archives, could be .tar.xz or .zip.
    encrypt_key: Path to the public key. GnuPG (gpg) is used when transmitting
      sensitive data. A public key must be provided.
  """
  source_dir = None
  source_file = None
  archived_dir = None
  recycle_dir = None
  project = None
  data_type = None
  notes = None
  duration = DEFAULT_DURATION
  delimiter = None
  compress_format = DEFAULT_FORMAT
  encrypt_key = None

  def __init__(self, data_type):
    self.data_type = data_type
    # Automatically infer properties for specific data_type.
    if data_type in DEFAULT_DELIMITER:
      logging.info('Using default delimiter %r fields for %r',
                   DEFAULT_DELIMITER[data_type], data_type)
      self.delimiter = DEFAULT_DELIMITER[data_type]

  def __str__(self):
    # Print properties for debugging purpose.
    return pprint.pformat({
        'source_dir': self.source_dir,
        'source_file': self.source_file,
        'archived_dir': self.archived_dir,
        'recycle_dir': self.recycle_dir,
        'project': self.project,
        'data_type': self.data_type,
        'notes': self.notes,
        'duration': self.duration,
        'delimiter': self.delimiter,
        'compress_format': self.compress_format,
        'encrypt_key': self.encrypt_key
        })

  def _CheckDirOrCreate(self, dir_path, create=False):
    """Checks the existence of a directory.

    If create flag is true, try to create the directory recursively.

    Args:
      dir_path: The path of the directory.
      create: True will try to create one recursively. False to ignore. Usually
        use False to force the user check if fields are set correctly instead
        of auto-fixing for them.

    Returns:
      True if the directory exists eventually.

    Raises:
      OSError: An error while accessing or creating the directory.
    """
    if not os.path.isdir(dir_path):
      logging.info("Path %r doesn't exist", dir_path)
      if create:
        try:
          # TODO(itspeter):
          #   Consider to use cros.factory.utils.file_utils.TryMakeDirs once
          #   Chromecast factory integrated with current factory framework.
          os.makedirs(dir_path)
        except OSError:
          logging.error("Exception found during the creation of %r. "
                        "Might be a racing or permission issue")
    return os.path.isdir(dir_path)

  def SetDir(self, dir_path, dir_type, create=False):
    """Sets the propeties that attributes to directory type.

    Args:
      dir_path: Path to the directory.
      dir_type: The property name in the class.
      create: Whether try to create if directory wasn't found.

    Raises:
      ArchiverFieldError with its failure reason.
    """
    dir_path = os.path.abspath(dir_path)
    if not hasattr(self, dir_type):
      raise ArchiverFieldError(
          "%r is not in the properties of ArchiverConfig" % dir_type)

    if not self._CheckDirOrCreate(dir_path, create):
      raise ArchiverFieldError("Can't access directory %r" % dir_path)
    setattr(self, dir_type, dir_path)

  def SetSourceFile(self, file_path):
    """Sets the source_file property.

    Args:
      file_path: Path to the file.

    Raises:
      ArchiverFieldError with its failure reason.
    """
    file_path = os.path.abspath(file_path)
    if not os.path.isfile(file_path):
      raise ArchiverFieldError("Cant's access %r" % file_path)
    self.source_file = file_path

  def SetProject(self, project):
    """Sets the project property.

    Args:
      project: The name of this project.

    Raises:
      ArchiverFieldError when regular expression doesn't meet.
    """
    VALID_REGEXP = r'^[A-Za-z0-9_-]+$'
    if not re.match(VALID_REGEXP, project):
      raise ArchiverFieldError(
          "Project field doesn't meet the regular expression %r" % VALID_REGEXP)
    self.project = project

  def SetNotes(self, notes):
    """Sets the notes property."""
    self.notes = str(notes)

  def SetDuration(self, duration):
    """Sets the duration property.

    Args:
      duration: An integer in seconds or a string in ALLOWED_DURATION.

    Raises:
      ArchiverFieldError when duraion is not an integer nor in ALLOWED_DURATION.
    """
    if not isinstance(duration, int):
      if duration in ALLOWED_DURATION:
        self.duration = ALLOWED_DURATION[duration]
      else:
        raise ArchiverFieldError(
          'duration %r is not supported at this time. '
          'We support the integer in seconds or the following: %s' % (
          duration, pprint.pformat(ALLOWED_DURATION.keys())))
    else:
      self.duration = duration

  def SetDelimiter(self, delimiter):
    """Sets the delimiter property."""
    self.delimiter = delimiter

  def SetCompressFormat(self, compress_format):
    """Sets the compress_format property.

    Raises:
      ArchiverFieldError if format is not supported.
    """
    if compress_format not in ALLOWED_FORMAT:
      raise ArchiverFieldError(
          'compress_format %r is not supported. We support the following:'
          '%s' % (compress_format, pprint.pformat(ALLOWED_FORMAT)))

  def SetEncryptKey(self, path_to_key):
    # TODO(itspeter):  Check GnuPG is installed.
    # TODO(itspeter):  Check public key file is exist and valid.
    # TODO(itspeter):  Write an unit test.
    pass

  def CheckPropertiesSufficient(self):
    """Checks if current properties are sufficient for an archiving cycle."""
    # TODO(itspeter):  Implement it.
    # TODO(itspeter):  Raise exception to Indicate where is possibly missing.


def GenerateConfig(config):
  """Generates ArchiverConfig from a config dictionary.

  In addition, checking basic correctness on those fields.

  Args:
    config: A dict object that represent the config for archiving.

  Returns:
    A list of ArchiverConfig.

  Raises:
    ArchiverConfig if any invalid fields found.
  """
  logging.debug("GenerateConfig got config: %s\n", pprint.pformat(config))
  archive_configs = []

  def _CheckAndSetFields(archive_config, fields):
    """Returns an ArchiverConfig.

    Args:
      archive_config: An ArchiverConfig object, data_type property must be
        set before calling this function.
      fields: A dictionary form of the configuration.

    Raises:
      ArchiverFieldError if any invalid.
    """
    def _SetDelimiter(target_config, value):
      logging.info('delimiter for %r has set manually to %r',
                   archive_config.data_type, value)
      target_config.SetDelimiter(value)

    SETTER_MAP = {
      'source_dir': lambda value: archive_config.SetDir(value, 'source_dir'),
      'source_file': archive_config.SetSourceFile,
      'archived_dir':
          lambda value: archive_config.SetDir(value, 'archived_dir'),
      'recycle_dir': lambda value: archive_config.SetDir(value, 'recycle_dir'),
      'project': archive_config.SetProject,
      'notes': archive_config.SetNotes,
      'duration': archive_config.SetDuration,
      'delimiter': lambda value: _SetDelimiter(archive_config, value),
      'compress_format': archive_config.SetCompressFormat,
      'encrypt_key': archive_config.SetEncryptKey
      }

    for field, value in fields.iteritems():
      SETTER_MAP[field](value)

  if not isinstance(config, dict):
    raise ArchiverFieldError(
        'YAML configuration is expected to be a dictionary')
  common_fields = config.get('common', None) or dict()

  # Check the existence of data_types.
  if not config.has_key('data_types'):
    raise ArchiverFieldError('Fields data_types are not found.')

  # Generate ArchiverConfig for each one in data_types.
  data_types_fields = config['data_types'] or dict()
  available_data_types = copy.copy(ALLOWED_DATA_TYPE)
  for data_type, fields in data_types_fields.iteritems():
    if data_type in available_data_types:
      available_data_types.remove(data_type)
    else:
      logging.info('%r is not supported at this time.\n'
                   'The following data_types are supported: %s',
                   data_type, pprint.pformat(ALLOWED_DATA_TYPE))
      raise ArchiverFieldError(
          'data_type %r is not supported at this time or '
          'there is a multiple definition' % data_type)
    logging.debug('Generating configuration for data type %r', data_type)
    archive_config = ArchiverConfig(data_type)
    _CheckAndSetFields(archive_config, common_fields)
    _CheckAndSetFields(archive_config, fields)

    logging.debug("data_type[%s] and its final configuration:\n%s\n",
                  data_type, archive_config)
    # Check if the properties are sufficient
    archive_config.CheckPropertiesSufficient()
    archive_configs.append(archive_config)
  return archive_configs


def main(argv):
  def IsValidYAMLFile(arg):
    """Help function to reject invalid YAML syntax"""
    if not os.path.exists(arg):
      error_str = 'The YAML config file %s does not exist!' % arg
      logging.error(error_str)
      raise IOError(error_str)
    else:
      logging.info('Verifying the YAML syntax for %r...', arg)
      try:
        with open(arg) as f:
          content = f.read()
        logging.debug('Raw YAML content:\n%r\n', content)
        yaml.load(content)
      except yaml.YAMLError as e:
        if hasattr(e, 'problem_mark'):
          logging.error('Possible syntax error is around: (line:%d, column:%d)',
                        e.problem_mark.line + 1, e.problem_mark.column + 1)
        raise e
    return arg

  top_parser = argparse.ArgumentParser(description='Log Archiver')
  sub_parsers = top_parser.add_subparsers(
      dest='sub_command', help='available sub-actions')

  parser_run = sub_parsers.add_parser('run', help='start the archiver')
  parser_dryrun = sub_parsers.add_parser(
      'dry-run', help='verify configuration without actually start archiver')
  # TODO(itspeter):
  #  Add arguments for run-once. run-once can run without a YAML configuration
  #  (i.e. directly from command line.)
  parser_runonce = sub_parsers.add_parser(  # pylint: disable=W0612
      'run-once', help='manually archive specific files')

  parser_run.add_argument(
      'yaml_config', action='store', type=IsValidYAMLFile,
      help='run archiver with the YAML configuration file')
  parser_dryrun.add_argument(
      'yaml_config', action='store', type=IsValidYAMLFile,
      help='path to YAML configuration file')
  args = top_parser.parse_args(argv)

  # Check fields.
  if args.sub_command == 'run' or args.sub_command == 'dry-run':
    with open(args.yaml_config) as f:
      logging.debug('Validating fields in %r', args.yaml_config)
      # TODO(itspeter): Complete the remaining logic for archiver.
      # pylint: disable=W0612
      configs = GenerateConfig(yaml.load(f.read()))


if __name__ == '__main__':
  # TODO(itspeter): Consider expose the logging level as an argument.
  logging.basicConfig(
      format=('[%(levelname)s] archiver:%(lineno)d %(asctime)s %(message)s'),
      level=logging.DEBUG, datefmt='%Y-%m-%d %H:%M:%S')
  main(sys.argv[1:])
