// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import bundle from '@app/bundle';
import {UpdateResourceFormPayload} from '@app/bundle/types';
import dashboard from '@app/dashboard';

import {Unionize} from '@common/utils';

export interface FormPayloadTypeMap {
  [dashboard.constants.ENABLE_UMPIRE_FORM]: {};
  [bundle.constants.UPLOAD_BUNDLE_FORM]: {};
  [bundle.constants.UPDATE_RESOURCE_FORM]: UpdateResourceFormPayload;
}

export type FormNames = keyof FormPayloadTypeMap;

export type FormDataType = Unionize<{
  [K in FormNames]: {formName: K} & {formPayload: FormPayloadTypeMap[K]};
}>;