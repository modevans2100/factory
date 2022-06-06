// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import produce from 'immer';
import {combineReducers} from 'redux';
import {ActionType, getType} from 'typesafe-actions';

import {basicActions as actions} from './actions';
import {PortResponse} from './types';

export interface PortState {
  ports: PortResponse;
}

type PortAction = ActionType<typeof actions>;

const portsReducer = produce((draft: PortState, action: PortAction) => {
  switch (action.type) {
    case getType(actions.receivePorts):
      return action.payload.ports;

    default:
      return;
  }
}, {});

export default combineReducers<PortState, PortAction>({
  ports: portsReducer,
});