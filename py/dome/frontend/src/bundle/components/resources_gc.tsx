// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import DeleteSweepIcon from '@mui/icons-material/DeleteSweep';
import Fab from '@mui/material/Fab';
import Snackbar from '@mui/material/Snackbar';
import React from 'react';
import {connect} from 'react-redux';

import {RootState} from '@app/types';

import {DispatchProps} from '@common/types';

import {
  closeGarbageCollectionSnackbar,
  startResourcesGarbageCollection,
} from '../actions';
import {getDeletedResources} from '../selectors';

type ResourcesGarbageCollectionProps =
  ReturnType<typeof mapStateToProps> & DispatchProps<typeof mapDispatchToProps>;

class ResourcesGarbageCollectionButton
  extends React.Component<ResourcesGarbageCollectionProps> {

  byteDisplay = (size: number) => {
    const units = ['B', 'KB', 'MB', 'GB'];
    for (const unit of units) {
      if (size < 1000) return `${size.toFixed(2)} ${unit}`;
      size /= 1000;
    }
    return `${size.toFixed(2)} GB`;
  };

  render() {
    const {resources} = this.props;
    return (
      <>
        <Fab onClick={this.props.startGarbageCollection}>
          <DeleteSweepIcon />
        </Fab>
        <Snackbar
          open={resources != null}
          onClose={this.props.closeSnackbar}
          message={resources != null &&
            <>
              <span>Released space: {this.byteDisplay(resources.size)}</span>
              {resources.files.map((file) => (
                <p>{file}</p>
              ))}
            </>}
        />
      </>
    );
  }
}

const mapStateToProps = (state: RootState) => ({
  resources: getDeletedResources(state),
});

const mapDispatchToProps = {
  startGarbageCollection: startResourcesGarbageCollection,
  closeSnackbar: closeGarbageCollectionSnackbar,
};

export default connect(
  mapStateToProps, mapDispatchToProps)(ResourcesGarbageCollectionButton);
