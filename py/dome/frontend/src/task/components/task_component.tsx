// Copyright 2016 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import RunningIcon from '@mui/icons-material/Autorenew';
import DismissIcon from '@mui/icons-material/CheckCircle';
import DeleteIcon from '@mui/icons-material/Delete';
import ErrorIcon from '@mui/icons-material/Error';
import CircularProgress from '@mui/material/CircularProgress';
import green from '@mui/material/colors/green';
import IconButton from '@mui/material/IconButton';
import {Theme} from '@mui/material/styles';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';

import {assertNotReachable} from '@common/utils';

import {isCancellable} from '../constants';
import {TaskProgress, TaskState} from '../types';

export const styles = (theme: Theme) => createStyles({
  colorAction: {
    fill: green[700],
  },
  description: {
    padding: theme.spacing(1),
    gridColumnStart: 1,
  },
});

interface TaskProps extends WithStyles<typeof styles> {
  state: TaskState;
  progress: TaskProgress;
  description: string;
  dismiss: () => void;
  retry: () => void;
  cancel: () => void;
}

const formatProgress = ({uploadedFiles, totalFiles}: TaskProgress) => (
  `Uploading file (${uploadedFiles + 1}/${totalFiles})`
);

const Task: React.SFC<TaskProps> = ({
  state,
  progress,
  description,
  cancel,
  dismiss,
  retry,
  classes,
}) => {
  let actionButton;
  switch (state) {
    case 'WAITING':
      actionButton = (
        <IconButton color="inherit" disabled>
          <RunningIcon />
        </IconButton>
      );
      break;
    case 'RUNNING_UPLOAD_FILE':
      actionButton = (
        <Tooltip title={formatProgress(progress)}>
          <IconButton>
            <CircularProgress
              variant="determinate"
              value={progress.uploadedSize / progress.totalSize * 100}
              size={20}
            />
          </IconButton>
        </Tooltip>
      );
      break;
    case 'RUNNING_WAIT_RESPONSE':
      actionButton = (
        <Tooltip title="Waiting response">
          <IconButton>
            <CircularProgress
              variant="indeterminate"
              size={20}
            />
          </IconButton>
        </Tooltip>
      );
      break;
    case 'SUCCEEDED':
      actionButton = (
        <Tooltip title="dismiss">
          <IconButton onClick={dismiss}>
            <DismissIcon
              color="action"
              classes={{
                colorAction: classes.colorAction,
              }}
            />
          </IconButton>
        </Tooltip>
      );
      break;
    case 'FAILED':
      actionButton = (
        <Tooltip title="retry">
          <IconButton onClick={retry}>
            <ErrorIcon color="error" />
          </IconButton>
        </Tooltip>
      );
      break;
    default:
      assertNotReachable(state);
  }
  return (
    <>
      <Typography variant="body2" className={classes.description} >
        {description}
      </Typography>
      <Tooltip title="cancel">
        <div>
          {/* We need an extra div so tooltip works when button is disabled. */}
          <IconButton
            onClick={cancel}
            disabled={!isCancellable(state)}
          >
            <DeleteIcon />
          </IconButton>
        </div>
      </Tooltip>
      {actionButton}
    </>
  );
};

export default withStyles(styles)(Task);
