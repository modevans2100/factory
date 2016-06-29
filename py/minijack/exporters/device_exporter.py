# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import minijack_common  # pylint: disable=W0611
from exporters.base import ExporterBase
from models import Device


STATUS_RUNNING = 'RUNNING'
STATUS_FINALIZED = 'FINALIZED'


class DeviceExporter(ExporterBase):
  """The exporter to create the Device table.

  TODO(waihong): Unit tests.
  """

  def Setup(self):
    """This method is called on Minijack start-up."""
    super(DeviceExporter, self).Setup()
    self._database.GetOrCreateTable(Device)

  def Handle_goofy_init(self, packet):
    """A handler for a goofy_init event."""
    if self._DoesFieldExist(packet, 'goofy_init_time'):
      # Skip updating if the goofy_init_time is already in the table.
      return
    self._UpdateField(packet, 'goofy_init_time', packet.event.get('TIME'))
    self._UpdateField(packet, 'minijack_status', STATUS_RUNNING)

  def Handle_update_device_data(self, packet):
    """A handler for a update_device_data event."""
    data = packet.event.get('data')
    if data:
      serial = data.get('serial_number')
      self._UpdateField(packet, 'serial', serial)

  def Handle_scan(self, packet):
    """A handler for a scan event."""
    # If not a barcode scan of the MLB serial number, skip it.
    if packet.event.get('key') != 'mlb_serial_number':
      return
    self._UpdateField(packet, 'mlb_serial', packet.event.get('value'))

  def Handle_call_shopfloor(self, packet):
    """A handler for a call_shopfloor event."""
    # The args[0] is always the MLB serial number for all methods.
    args = packet.event.get('args')
    if args and len(args) >= 1:
      mlb_serial = args[0]
      self._UpdateField(packet, 'mlb_serial', mlb_serial)

  def Handle_hwid(self, packet):
    """A handler for a hwid event."""
    self._UpdateField(packet, 'hwid', packet.event.get('hwid'))

  def Handle_verified_hwid(self, packet):
    """A handler for a verified_hwid event."""
    self.Handle_hwid(packet)

  def Handle_system_status(self, packet):
    """A handler for a system_status event."""
    self._UpdateField(packet, 'ips', packet.event.get('ips'), with_time=True)

  def Handle_start_test(self, packet):
    """A handler for a start_test event."""
    self._UpdateField(packet, 'latest_test', packet.event.get('path'),
                      with_time=True)

  def Handle_end_test(self, packet):
    """A handler for a end_test event."""
    condition = Device(device_id=packet.preamble.get('device_id'))
    row = self._database.GetOne(condition)
    # Not exist in the table, use the one just created with device_id.
    if not row:
      row = condition
    status = packet.event.get('status')
    row.latest_ended_test = packet.event.get('path')
    row.latest_ended_status = status
    # The count_passed/count_failed may not be the accurate values due to
    # duplicated log. The accurate values are in the Test table. The values
    # in the Device table are just approximates to quickly know their status.
    if status == 'PASSED':
      row.count_passed = row.count_passed + 1
    elif status == 'FAILED':
      row.count_failed = row.count_failed + 1
    self._database.UpdateOrInsert(row)

  def Handle_test_states(self, packet):
    self._UpdateField(packet, 'minijack_status', STATUS_FINALIZED)

  def Handle_note(self, packet):
    row = Device(
        device_id=packet.preamble.get('device_id'),
        latest_note_level=packet.event.get('level'),
        latest_note_name=packet.event.get('name'),
        latest_note_text=packet.event.get('text'),
        latest_note_time=packet.event.get('TIME'),
    )
    self._database.UpdateOrInsert(row)

  def _UpdateField(self, packet, field_name, field_value, with_time=False):
    """Updates the field to the table.

    Args:
      packet: An EventPacket object.
      field_name: The field name.
      field_value: The value of field to update.
      with_time: True to update the corresponding time field, i.e.
                 "{field_name}_time".
    """
    if not field_value:
      return
    row = Device(device_id=packet.preamble.get('device_id'))
    setattr(row, field_name, field_value)
    if with_time:
      field_name_time = field_name + '_time'
      setattr(row, field_name_time, packet.event.get('TIME'))
    self._database.UpdateOrInsert(row)

  def _DoesFieldExist(self, packet, field):
    """Checks if a given field already in the table.

    Args:
      packet: An EventPacket object.
      field: A string of field name.

    Returns:
      True if the field exists.
    """
    row = self._database(Device).Filter(
        device_id=packet.preamble.get('device_id')).GetOne()
    if row:
      return bool(getattr(row, field))
    else:
      return False