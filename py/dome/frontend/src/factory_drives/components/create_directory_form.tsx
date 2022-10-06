// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import React from 'react';
import {connect} from 'react-redux';
import {
  FormErrors,
  InjectedFormProps,
  reduxForm,
  submit,
} from 'redux-form';

import formDialog from '@app/form_dialog';
import project from '@app/project';
import {RootState} from '@app/types';

import ReduxFormTextField from '@common/components/redux_form_text_field';
import {HiddenSubmitButton, validateDirectoryName} from '@common/form';
import {DispatchProps} from '@common/types';

import {startCreateDirectory} from '../actions';
import {CREATE_DIRECTORY_FORM} from '../constants';
import {CreateDirectoryRequest} from '../types';

const validate = (values: CreateDirectoryRequest) => {
  const errors: FormErrors<CreateDirectoryRequest> = {};
  if (!validateDirectoryName(values.name)) {
    errors['name'] =
      'Invalid directory name. It should only contain: A-Z, a-z, 0-9, -, _';
  }
  return errors;
};

const InnerFormComponent: React.SFC<InjectedFormProps<CreateDirectoryRequest>> =
  ({handleSubmit}) => (
    <form onSubmit={handleSubmit}>
      <ReduxFormTextField
        name="name"
        label="name"
        type="string"
      />
      <HiddenSubmitButton />
    </form>
  );

const InnerForm = reduxForm<CreateDirectoryRequest>({
  form: CREATE_DIRECTORY_FORM,
  validate,
})(InnerFormComponent);

interface CreateDirectoryFormOwnProps {
  dirId: number | null;
}

type CreateDirectoryFormProps =
  CreateDirectoryFormOwnProps &
  ReturnType<typeof mapStateToProps> &
  DispatchProps<typeof mapDispatchToProps>;

const CreateDirectoryForm: React.SFC<CreateDirectoryFormProps> = ({
  open,
  cancelCreate,
  createDirectory,
  submitForm,
  dirId,
}) => {
  const initialValues = {
    parentId: dirId,
  };
  return (
    <Dialog open={open} onClose={cancelCreate}>
      <DialogTitle>Create Directory</DialogTitle>
      <DialogContent>
        <InnerForm
          onSubmit={createDirectory}
          initialValues={initialValues}
        />
      </DialogContent>
      <DialogActions>
        <Button color="primary" onClick={submitForm}>Create</Button>
        <Button onClick={cancelCreate}>Cancel</Button>
      </DialogActions>
    </Dialog>
  );
};

const isFormVisible =
  formDialog.selectors.isFormVisibleFactory(CREATE_DIRECTORY_FORM);

const mapStateToProps = (state: RootState) => ({
  open: isFormVisible(state),
  project: project.selectors.getCurrentProject(state),
});

const mapDispatchToProps = {
  submitForm: () => submit(CREATE_DIRECTORY_FORM),
  cancelCreate: () => formDialog.actions.closeForm(CREATE_DIRECTORY_FORM),
  createDirectory: startCreateDirectory,
};

export default connect(
  mapStateToProps, mapDispatchToProps)(CreateDirectoryForm);
