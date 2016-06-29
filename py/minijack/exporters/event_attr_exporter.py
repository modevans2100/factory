# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

import minijack_common  # pylint: disable=W0611
import db
import db.sqlite
from datatypes import EventPacket
from exporters.base import ExporterBase
from models import Event, Attr


class EventAttrExporter(ExporterBase):
  """The exporter to create the Event and Attr tables.

  TODO(waihong): Unit tests.
  """

  def Setup(self):
    super(EventAttrExporter, self).Setup()
    self._database.GetOrCreateTable(Event)
    self._database.GetOrCreateTable(Attr)

  def Handle_all(self, packet):
    """A handler for all event types."""
    # Just insert the row for speed-up. May raises an exception if the row
    # already exists.
    try:
      # Insert to Event first. If it finds duplication, skips Attr insertion.
      self._InsertEvent(packet)
      self._InsertAttr(packet)
    except db.sqlite.IntegrityError:
      logging.warn('The Event/Attr (%s) already exists in the table',
                   packet.GetEventId())

  def _InsertEvent(self, packet):
    """Retrieves event information and inserts to Event table"""
    row = Event(
        event_id=packet.GetEventId(),
        device_id=packet.preamble.get('device_id'),
        time=packet.event.get('TIME'),
        event=packet.event.get('EVENT'),
        seq=int(packet.event.get('SEQ')),
        # Backward compatibile with the old tags, i.e. log_id and filename.
        log_id=(packet.event.get('LOG_ID') or
                packet.preamble.get('log_id')),
        prefix = (packet.event.get('PREFIX') or
                  packet.preamble.get('filename', '').split('-')[0]),
        boot_id = packet.preamble.get('boot_id'),
        boot_sequence = int(packet.preamble.get('boot_sequence')),
        factory_md5sum = packet.preamble.get('factory_md5sum'),
        reimage_id = (packet.preamble.get('reimage_id') or
                      packet.preamble.get('image_id')),
    )
    self._database.Insert(row)

  def _InsertAttr(self, packet):
    """Retrieves attr information and inserts to Attr table"""
    RESERVED_PATH = ('EVENT', 'SEQ', 'TIME', 'PREFIX', 'LOG_ID')
    rows = []
    # As the event is a tree struct which contains dicts or lists,
    # we flatten it first. The hierarchy is recorded in the Attr column.
    for attr, value in EventPacket.FlattenAttr(packet.event):
      if attr not in RESERVED_PATH:
        row = Attr(
            event_id=packet.GetEventId(),
            attr=_ToAsciiString(attr),
            value=_ToAsciiString(value),
        )
        rows.append(row)
    if rows:
      self._database.InsertMany(rows)


def _ToAsciiString(value):
  """Convert any type object to an ascii string."""
  if isinstance(value, str):
    return value.encode('string_escape')
  elif isinstance(value, unicode):
    return value.encode('unicode_escape')
  else:
    return str(value)