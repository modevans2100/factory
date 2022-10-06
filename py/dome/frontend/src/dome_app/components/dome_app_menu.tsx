// Copyright 2016 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Drawer from '@mui/material/Drawer';
import MenuList from '@mui/material/MenuList';
import {Theme} from '@mui/material/styles';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';
import {connect} from 'react-redux';

import auth from '@app/auth';
import project from '@app/project';
import {RootState} from '@app/types';

import MenuSubheader from '@common/components/menu_subheader';

import DomeAppMenuItem from './dome_app_menu_item';

const styles = (theme: Theme) => createStyles({
  toolbarSpace: theme.mixins.toolbar,
  nested: {
    paddingLeft: theme.spacing(4),
  },
});

interface DomeAppMenuOwnProps {
  width: number;
  open: boolean;
}

type DomeAppMenuProps =
  DomeAppMenuOwnProps &
  WithStyles<typeof styles> &
  ReturnType<typeof mapStateToProps>;

const DomeAppMenu: React.SFC<DomeAppMenuProps> = ({
  isLoggedIn,
  project,
  open,
  classes,
  width,
}) => {
  return (
    <Drawer
      variant="persistent"
      open={open}
      PaperProps={{elevation: 2, style: {width}}}
    >
      <div className={classes.toolbarSpace} />
      {isLoggedIn && (
        <MenuList disablePadding>
          {project && [
            <MenuSubheader key="header">
              {project.name}
            </MenuSubheader>,
            <DomeAppMenuItem
              app="DASHBOARD_APP"
              key="DASHBOARD_APP"
              className={classes.nested}
            >
              Dashboard
            </DomeAppMenuItem>,
            <DomeAppMenuItem
              app="BUNDLES_APP"
              key="BUNDLES_APP"
              className={classes.nested}
              disabled={!project.umpireReady}
            >
              Bundles {project.umpireEnabled &&
                !project.umpireReady && '(activating...)'}
            </DomeAppMenuItem>,
            <DomeAppMenuItem
              app="FACTORY_DRIVE_APP"
              key="FACTORY_DRIVE_APP"
              className={classes.nested}
              disabled={!project.umpireReady}
            >
              Factory Drives {project.umpireEnabled &&
                !project.umpireReady && '(activating...)'}
            </DomeAppMenuItem>,
            <DomeAppMenuItem
              app="LOG_APP"
              key="LOG_APP"
              className={classes.nested}
              disabled={!project.umpireReady}
            >
              Logs {project.umpireEnabled &&
                !project.umpireReady && '(activating...)'}
            </DomeAppMenuItem>,
            <DomeAppMenuItem
              app="SYNC_STATUS_APP"
              key="SYNC_STATUS_APP"
              className={classes.nested}
              disabled={!project.umpireReady}
              divider
            >
              Sync Status {project.umpireEnabled &&
                !project.umpireReady && '(activating...)'}
            </DomeAppMenuItem>,
          ]}

          <DomeAppMenuItem app="PROJECTS_APP" divider>
            Select project
          </DomeAppMenuItem>
          <DomeAppMenuItem app="CONFIG_APP">
            Config
          </DomeAppMenuItem>
        </MenuList>
      )}
    </Drawer>
  );
};

const mapStateToProps = (state: RootState) => ({
  isLoggedIn: auth.selectors.isLoggedIn(state),
  project: project.selectors.getCurrentProjectObject(state),
});

export default connect(mapStateToProps)(withStyles(styles)(DomeAppMenu));
