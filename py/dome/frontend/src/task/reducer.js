// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Immutable from 'immutable';

import actionTypes from './actionTypes';
import {TaskStates} from './constants';

const INITIAL_STATE = Immutable.Map({
  tasks: Immutable.OrderedMap(),
});

export default (state = INITIAL_STATE, action) => {
  switch (action.type) {
    case actionTypes.CREATE_TASK:
      return state.setIn(['tasks', action.taskID], Immutable.fromJS({
        state: TaskStates.WAITING,
        description: action.description,
        method: action.method,
        url: action.url,
        contentType: action.contentType,
        progress: {
          totalFiles: 0,
          totalSize: 0,
          uploadedFiles: 0,
          uploadedSize: 0,
        },
      }));

    case actionTypes.CHANGE_TASK_STATE:
      return state.setIn(
          ['tasks', action.taskID, 'state'], action.state);

    case actionTypes.DISMISS_TASK:
      return state.deleteIn(['tasks', action.taskID]);

    case actionTypes.UPDATE_TASK_PROGRESS:
      return state.mergeIn(
          ['tasks', action.taskID, 'progress'], action.progress);

    default:
      return state;
  }
};
