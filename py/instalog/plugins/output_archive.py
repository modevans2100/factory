#!/usr/bin/python2
#
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Output archive plugin.

An archive plugin to backup all events and their attachments to a tar.gz file.

The archive name:
  'InstalogEvents_' + year + month + day + hour + minute + second

The archive structure:
  InstalogEvents_YYYYmmddHHMMSS.tar.gz
    InstalogEvents_YYYYmmddHHMMSS/
      events.json
      attachments/  # Will not have this dir if no attachment.
        000_${EVENT_0_ATTACHMENT_0_NAME}
        000_${EVENT_0_ATTACHMENT_1_NAME}
        001_${EVENT_1_ATTACHMENT_0_NAME}
        001_${EVENT_1_ATTACHMENT_1_NAME}
        ...
"""

from __future__ import print_function

import datetime
import os
import shutil
import tarfile

import instalog_common  # pylint: disable=unused-import
from instalog import plugin_base
from instalog.utils.arg_utils import Arg
from instalog.utils import file_utils
from instalog.utils import time_utils


_ARCHIVE_MESSAGE_INTERVAL = 60  # 60sec
_DEFAULT_INTERVAL = 1 * 60 * 60  # 1hr
_DEFAULT_MAX_SIZE = 200 * 1024 * 1024  # 200mb


class OutputArchive(plugin_base.OutputPlugin):

  ARGS = [
      Arg('interval', (int, float),
          'How long to wait, in seconds, before creating the next archive.',
          default=_DEFAULT_INTERVAL),
      Arg('max_size', int,
          'If the total_size bigger than max_size, archive these events.',
          default=_DEFAULT_MAX_SIZE),
      Arg('enable_disk', bool,
          'Whether or not to save the archive to disk.  True by default.',
          default=True),
      Arg('target_dir', (str, unicode),
          'The directory in which to store archives.  Uses the plugin\'s '
          'data directory by default.',
          default=None),
      Arg('enable_gcs', bool,
          'Whether or not to upload the archive to Google Cloud Storage.  '
          'False by default.',
          default=False),
      Arg('key_path', (str, unicode),
          'Path to Cloud Storage service account JSON key file.',
          default=None),
      Arg('gcs_target_dir', (str, unicode),
          'Path to the target bucket and directory on Google Cloud Storage.',
          default=None),
  ]

  def __init__(self, *args, **kwargs):
    self._gcs = None
    super(OutputArchive, self).__init__(*args, **kwargs)

  def SetUp(self):
    """Sets up the plugin."""
    if not self.args.enable_disk and not self.args.enable_gcs:
      raise ValueError('Please enable at least one of "enable_disk" or '
                       '"enable_gcs"')

    if not self.args.enable_disk and self.args.target_dir:
      raise ValueError('If specifying a "target_dir", "enable_disk" must '
                       'be set to True')
    # If saving to disk, ensure that the target_dir exists.
    if self.args.enable_disk and self.args.target_dir is None:
      self.args.target_dir = self.GetDataDir()
    if self.args.target_dir and not os.path.isdir(self.args.target_dir):
      os.makedirs(self.args.target_dir)

    if not self.args.enable_gcs:
      if self.args.key_path or self.args.gcs_target_dir:
        raise ValueError('If specifying a "key_path" or "gcs_target_dir", '
                         '"enable_gcs" must be set to True')
    if self.args.enable_gcs:
      if not self.args.key_path or not self.args.gcs_target_dir:
        raise ValueError('If "enable_gcs" is True, "key_path" and '
                         '"gcs_target_dir" must be provided')

      from instalog.utils import gcs_utils
      self._gcs = gcs_utils.CloudStorage(self.args.key_path)

  def Main(self):
    """Main thread of the plugin."""
    while not self.IsStopping():
      if not self.PrepareAndArchive():
        self.Sleep(1)

  def ProcessEvent(self, event_id, event, base_dir):
    """Copies an event's attachments and returns its serialized form."""
    for att_id, att_path in event.attachments.iteritems():
      if os.path.isfile(att_path):
        att_name = os.path.basename(att_path)
        att_newpath = os.path.join('attachments',
                                   '%03d_%s' % (event_id, att_name))
        shutil.copyfile(att_path, os.path.join(base_dir, att_newpath))
        event.attachments[att_id] = att_newpath
    return event.Serialize()

  def GetEventAttachmentSize(self, event):
    """Returns the total size of given event's attachments."""
    total_size = 0
    for _unused_att_id, att_path in event.attachments.iteritems():
      if os.path.isfile(att_path):
        total_size += os.path.getsize(att_path)
    return total_size

  def PrepareAndArchive(self):
    """Retrieves events, and archives them."""
    event_stream = self.NewStream()
    if not event_stream:
      return False

    with file_utils.TempDirectory(prefix='instalog_archive_') as base_dir:
      self.info('Creating temporary directory: %s', base_dir)
      # Create the attachments directory.
      att_dir = os.path.join(base_dir, 'attachments')
      os.mkdir(att_dir)

      # In order to save memory, write directly to a temp file on disk.
      with open(os.path.join(base_dir, 'events.json'), 'w') as events_f:
        num_events = 0
        total_size = 0
        time_last = time_utils.MonotonicTime()
        for event in event_stream.iter(timeout=self.args.interval):
          serialized_event = self.ProcessEvent(num_events, event, base_dir)
          attachment_size = self.GetEventAttachmentSize(event)
          events_f.write(serialized_event + '\n')

          total_size += len(serialized_event) + attachment_size
          num_events += 1
          self.debug('num_events = %d', num_events)

          # Throttle our status messages.
          time_now = time_utils.MonotonicTime()
          if (time_now - time_last) >= _ARCHIVE_MESSAGE_INTERVAL:
            time_last = time_now
            self.info('Currently at %.2f%% of %.2fMB before archiving',
                      100.0 * total_size / self.args.max_size,
                      self.args.max_size / 1024.0 / 1024)
          if total_size >= self.args.max_size:
            break

      if self.IsStopping():
        self.info('Plugin is stopping! Abort %d events', num_events)
        event_stream.Abort()
        return False

      # Create the archive.
      if num_events > 0:
        cur_time = datetime.datetime.now()
        archive_name = cur_time.strftime('InstalogEvents_%Y%m%d%H%M%S')
        archive_filename = '%s.tar.gz' % archive_name
        with file_utils.UnopenedTemporaryFile(
            prefix='instalog_archive_', suffix='.tar.gz') as tmp_archive:
          self.info('Creating temporary archive file: %s', tmp_archive)
          self.info('Archiving %d events in %s', num_events, archive_name)
          with tarfile.open(tmp_archive, 'w:gz') as tar:
            tar.add(base_dir, arcname=archive_name)

          # What should we do with the archive?
          if self.args.enable_gcs:
            gcs_target_dir = self.args.gcs_target_dir.strip('/')
            gcs_target_path = '/%s/%s' % (gcs_target_dir, archive_filename)
            if not self._gcs.UploadFile(
                tmp_archive, gcs_target_path, overwrite=True):
              self.error('Unable to upload to GCS, aborting')
              event_stream.Abort()
              return False
          if self.args.enable_disk:
            target_path = os.path.join(self.args.target_dir, archive_filename)
            self.info('Saving archive to: %s', target_path)
            shutil.move(tmp_archive, target_path)

    self.info('Commit %d events', num_events)
    event_stream.Commit()
    return True


if __name__ == '__main__':
  plugin_base.main()