// Copyright 2019 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import CardContent from '@mui/material/CardContent';
import CircularProgress from '@mui/material/CircularProgress';
import green from '@mui/material/colors/green';
import IconButton from '@mui/material/IconButton';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import {Theme} from '@mui/material/styles';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import RunningIcon from '@mui/icons-material/Autorenew';
import SuccessIcon from '@mui/icons-material/CheckCircle';
import DeleteIcon from '@mui/icons-material/Delete';
import ErrorIcon from '@mui/icons-material/Error';
import CollapseIcon from '@mui/icons-material/ExpandLess';
import ExpandIcon from '@mui/icons-material/ExpandMore';
import ReportIcon from '@mui/icons-material/ReportProblem';
import classNames from 'classnames';
import React from 'react';

import {assertNotReachable} from '@common/utils';

import {
  ComponentState,
  ComponentType,
} from '../types';

const styles = (theme: Theme) => createStyles({
  colorAction: {
    fill: green[700],
  },
  cardContent: {
    display: 'grid',
    gridTemplateColumns: '12px 1fr 96px 48px',
    alignItems: 'center',
  },
  normalGrid: {
    gridTemplateAreas: '"text text icon expand"',
  },
  listItemGrid: {
    gridTemplateAreas: '". text icon expand"',
  },
  item: {
    paddingTop: '0px',
    paddingBottom: '0px',
  },
  text: {
    flex: 1,
    gridArea: 'text',
  },
  icon: {
    gridArea: 'icon',
  },
  expand: {
    gridArea: 'expand',
  },
  heading: {
    fontSize: theme.typography.pxToRem(18),
  },
});

export interface LogComponentOwnProps {
  message: string;
  componentType: ComponentType;
  componentState: ComponentState;
  expanded?: boolean;
  progress?: number;
  toggleExpand?: () => void;
  retry?: () => void;
  remove?: () => void;
}

type LogComponentProps =
  LogComponentOwnProps &
  WithStyles<typeof styles>;

class LogComponent extends React.Component<LogComponentProps> {
  render() {
    const {
      classes,
      message,
      componentType,
      componentState,
      toggleExpand,
      retry,
      remove,
      progress,
      expanded,
    } = this.props;

    let actionButton;
    switch (componentState) {
      case 'SUCCEEDED':
        actionButton = (
          <Tooltip title="succeeded">
            <span>
              <IconButton disabled>
                <SuccessIcon
                  color="action"
                  classes={{
                    colorAction: classes.colorAction,
                  }}
                />
              </IconButton>
            </span>
          </Tooltip>
        );
        break;
      case 'PROCESSING':
        actionButton = (
          <Tooltip title="processing">
            <span>
              <IconButton disabled>
                <CircularProgress
                  value={progress}
                  variant={progress ? 'determinate' : 'indeterminate'}
                  size={20}
                />
              </IconButton>
            </span>
          </Tooltip>
        );
        break;
      case 'FAILED':
        actionButton = (
          <Tooltip title={retry === undefined ? 'failed' : 'retry'}>
            <span>
              <IconButton
                onClick={retry}
                disabled={retry === undefined}
              >
                <ErrorIcon color="error" />
              </IconButton>
            </span>
          </Tooltip>
        );
        break;
      case 'REPORT':
        actionButton = (
          <Tooltip title="report">
            <span>
              <IconButton disabled>
                <ReportIcon color="action" />
              </IconButton>
            </span>
          </Tooltip>
        );
        break;
      case 'WAITING':
        actionButton = (
          <IconButton color="inherit" disabled>
            <RunningIcon />
          </IconButton>
        );
        break;
      default:
        assertNotReachable(componentState);
    }

    let cardClass;
    let renderedMessage;
    switch (componentType) {
      case 'header':
        cardClass = classNames(classes.cardContent,
                               classes.normalGrid);
        renderedMessage = (
          <Typography className={classes.heading}>
            {message}
          </Typography>
        );
        break;
      case 'item':
        cardClass = classNames(classes.cardContent,
                               classes.item,
                               classes.normalGrid);
        renderedMessage = (
          <Typography variant="body1">
            {message}
          </Typography>
        );
        break;
      case 'list-item':
        cardClass = classNames(classes.cardContent,
                               classes.item,
                               classes.listItemGrid);
        renderedMessage = (
          <Typography variant="body2">
            {message}
          </Typography>
        );
        break;
      default:
        assertNotReachable(componentType);
    }

    const expandCollapseButton = (
      <div className={classes.expand}>
        <IconButton onClick={toggleExpand}>
          {expanded ? <CollapseIcon /> : <ExpandIcon />}
        </IconButton>
      </div>
    );

    return (
      <CardContent className={cardClass}>
        <div className={classes.text}>
          {renderedMessage}
        </div>
        <div className={classes.icon}>
          <Tooltip title="remove">
            <span>
              <IconButton
                onClick={remove}
                disabled={
                  (remove === undefined ||
                   componentState === 'WAITING' ||
                   componentState === 'PROCESSING')}
              >
                <DeleteIcon/>
              </IconButton>
            </span>
          </Tooltip>
          {actionButton}
        </div>
        {(componentType === 'header') && expandCollapseButton}
      </CardContent>
    );
  }
}

export default withStyles(styles)(LogComponent);
