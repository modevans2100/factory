// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {RootState} from '@app/types';

import {NAME} from './constants';
import {FormDialogState} from './reducer';
import {FormNames} from './types';

export const localState = (state: RootState): FormDialogState => state[NAME];

export const isFormVisibleFactory = (name: FormNames) =>
  (state: RootState): boolean => localState(state).visibility[name] || false;

export const getFormPayloadFactory = (name: FormNames) =>
  (state: RootState) => localState(state).payload[name] || {};