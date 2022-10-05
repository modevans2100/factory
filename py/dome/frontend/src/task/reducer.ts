// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import produce from 'immer';
import {combineReducers} from 'redux';
import {ActionType, getType} from 'typesafe-actions';

import {basicActions as actions} from './actions';
import {Task} from './types';

export interface TaskState {
  tasks: Task[];
}

type TaskAction = ActionType<typeof actions>;

const findTaskIndex = (tasks: Task[], taskId: string) => {
  return tasks.findIndex((task) => task.taskId === taskId);
};

const tasksReducer = produce(
  (draft: Task[], action: TaskAction) => {
    switch (action.type) {
      case getType(actions.createTaskImpl): {
        const {
          taskId,
          description,
          method,
          url,
          warningMessage,
        } = action.payload;
        draft.push({
          taskId,
          state: 'WAITING',
          description,
          warningMessage,
          method,
          url,
          progress: {
            totalFiles: 0,
            totalSize: 0,
            uploadedFiles: 0,
            uploadedSize: 0,
          },
        });
        return;
      }

      case getType(actions.changeTaskState): {
        const {taskId, state} = action.payload;
        const taskIndex = findTaskIndex(draft, taskId);
        if (taskIndex > -1) {
          draft[taskIndex].state = state;
        }
        return;
      }

      case getType(actions.changeTaskWarningMessage): {
        const {taskId, warningMessage} = action.payload;
        const taskIndex = findTaskIndex(draft, taskId);
        if (taskIndex > -1) {
          draft[taskIndex].warningMessage = warningMessage;
        }
        return;
      }

      case getType(actions.dismissTaskImpl): {
        const taskIndex = findTaskIndex(draft, action.payload.taskId);
        if (taskIndex > -1) {
          draft.splice(taskIndex, 1);
        }
        return;
      }

      case getType(actions.updateTaskProgress): {
        const {taskId, progress} = action.payload;
        const taskIndex = findTaskIndex(draft, taskId);
        if (taskIndex > -1) {
          Object.assign(draft[taskIndex].progress, progress);
        }
        return;
      }

      default:
        return;
    }
  }, []);

export default combineReducers({
  tasks: tasksReducer,
});
