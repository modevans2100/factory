// Copyright 2017 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from '@material-ui/core/Button';
import Card from '@material-ui/core/Card';
import CardActions from '@material-ui/core/CardActions';
import CardContent from '@material-ui/core/CardContent';
import CardHeader from '@material-ui/core/CardHeader';
import FormControlLabel from '@material-ui/core/FormControlLabel';
import Switch from '@material-ui/core/Switch';
import React from 'react';
import {connect} from 'react-redux';

import auth from '@app/auth';
import {RootState} from '@app/types';

import {DispatchProps} from '@common/types';

import {
  disableMroute,
  disableTftp,
  enableMroute,
  enableTftp,
  fetchConfig,
} from '../actions';
import {
  isConfigUpdating,
  isMrouteEnabled,
  isTftpEnabled,
} from '../selectors';

type ConfigAppProps =
  ReturnType<typeof mapStateToProps> & DispatchProps<typeof mapDispatchToProps>;

class ConfigApp extends React.Component<ConfigAppProps> {
  componentDidMount() {
    this.props.fetchConfig();
  }

  render() {
    const {
      isMrouteEnabled,
      isTftpEnabled,
      isConfigUpdating,
      disableMroute,
      disableTftp,
      enableMroute,
      enableTftp,
      logout,
    } = this.props;

    return (
      <Card>
        <CardHeader title="Config" />
        <CardContent>
          <FormControlLabel
            control={
              <Switch
                color="primary"
                checked={isTftpEnabled}
                onChange={isTftpEnabled ? disableTftp : enableTftp}
                disabled={isConfigUpdating}
              />
            }
            label="TFTP server"
          />
          <FormControlLabel
            control={
              <Switch
                color="primary"
                checked={isMrouteEnabled}
                onChange={isMrouteEnabled ? disableMroute : enableMroute}
                disabled={isConfigUpdating}
              />
            }
            label="Multicast Routing"
          />
        </CardContent>
        <CardActions>
          <Button color="primary" size="small" onClick={logout}>
            logout
          </Button>
        </CardActions>
      </Card>
    );
  }
}

const mapStateToProps = (state: RootState) => ({
  isTftpEnabled: isTftpEnabled(state),
  isMrouteEnabled: isMrouteEnabled(state),
  isConfigUpdating: isConfigUpdating(state),
});

const mapDispatchToProps = {
  disableMroute,
  disableTftp,
  enableMroute,
  enableTftp,
  fetchConfig,
  logout: auth.actions.logout,
};

export default connect(mapStateToProps, mapDispatchToProps)(ConfigApp);
