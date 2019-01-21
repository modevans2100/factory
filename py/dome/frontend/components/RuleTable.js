// Copyright 2016 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import ChipInput from 'material-ui-chip-input';
import Immutable from 'immutable';
import React from 'react';
import {Table, TableBody, TableHeaderColumn,
        TableRow, TableRowColumn} from 'material-ui/Table';

var RuleTable = React.createClass({
  propTypes: {
    rules: React.PropTypes.instanceOf(Immutable.Map).isRequired,
    changeRules: React.PropTypes.func.isRequired
  },

  handleAdd(key, value) {
    var rules = this.props.rules.toJS();
    if (!(key in rules)) {
      rules[key] = [];
    }
    rules[key].push(value);
    this.props.changeRules(rules);
  },

  handleDelete(key, value) {
    var rules = this.props.rules.toJS();
    var index = rules[key].indexOf(value);
    if (index >= 0) {
      rules[key].splice(index, 1);
      this.props.changeRules(rules);
    }
  },

  render: function() {
    // make sure every key exists
    var rules = this.props.rules.mergeDeep(Immutable.fromJS({
      'macs': [],
      'serialNumbers': [],
      'mlbSerialNumbers': []
    })).toJS();

    return (
      <Table selectable={false}>
        <TableBody displayRowCheckbox={false}>
          <TableRow>
            <TableHeaderColumn>MAC</TableHeaderColumn>
            <TableRowColumn>
              <ChipInput
                value={rules['macs']}
                onRequestAdd={m => this.handleAdd('macs', m)}
                onRequestDelete={m => this.handleDelete('macs', m)}
              />
            </TableRowColumn>
          </TableRow>
          <TableRow>
            <TableHeaderColumn>SN</TableHeaderColumn>
            <TableRowColumn>
              <ChipInput
                value={rules['serialNumbers']}
                onRequestAdd={s => this.handleAdd('serialNumbers', s)}
                onRequestDelete={s => this.handleDelete('serialNumbers', s)}
              />
            </TableRowColumn>
          </TableRow>
          <TableRow>
            <TableHeaderColumn>MLB SN</TableHeaderColumn>
            <TableRowColumn>
              <ChipInput
                value={rules['mlbSerialNumbers']}
                onRequestAdd={s => this.handleAdd('mlbSerialNumbers', s)}
                onRequestDelete={
                  s => this.handleDelete('mlbSerialNumbers', s)
                }
              />
            </TableRowColumn>
          </TableRow>
        </TableBody>
      </Table>
    );
  }
});

export default RuleTable;