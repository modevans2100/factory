// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import TextField from 'material-ui/TextField';
import PropTypes from 'prop-types';
import React from 'react';
import {fieldPropTypes} from 'redux-form';

export const renderTextField = ({
  input,
  label,
  meta: {error, touched},
  type = 'text',
  description = '',
}) => (
  <TextField
    fullWidth={true}
    floatingLabelText={label}
    type={type}
    hintText={description}
    errorText={touched && error}
    {...input}
  />
);

renderTextField.propTypes = {
  label: PropTypes.string.isRequired,
  type: PropTypes.string,
  description: PropTypes.string,
  ...fieldPropTypes,
};

export const validateRequired = (value) => value ? undefined : 'Required';
