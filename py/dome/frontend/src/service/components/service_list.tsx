// Copyright 2017 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import ExpandLess from '@mui/icons-material/ExpandLess';
import ExpandMore from '@mui/icons-material/ExpandMore';
import Card from '@mui/material/Card';
import Collapse from '@mui/material/Collapse';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import produce from 'immer';
import React from 'react';
import {connect} from 'react-redux';

import {RootState} from '@app/types';

import {DispatchProps} from '@common/types';

import {fetchServices, fetchServiceSchemata, updateService} from '../actions';
import {getServices, getServiceSchemata} from '../selectors';

import ServiceForm from './service_form';

type ServiceListProps =
  ReturnType<typeof mapStateToProps> & DispatchProps<typeof mapDispatchToProps>;

interface ServiceListStates {
  expanded: {[name: string]: boolean};
}

class ServiceList extends React.Component<ServiceListProps, ServiceListStates> {
  state: ServiceListStates = {
    expanded: {},
  };

  componentDidMount() {
    this.props.fetchServices();
    this.props.fetchServiceSchemata();
  }

  toggleExpand = (name: string) => {
    this.setState({
      expanded: produce(this.state.expanded, (expanded) => {
        expanded[name] = !expanded[name];
      }),
    });
  }

  render() {
    const {
      schemata,
      services,
      updateService,
    } = this.props;

    return (
      <>
        {Object.keys(schemata).sort().map((k, i) => {
          const schema = schemata[k];
          const service = {
            active: services.hasOwnProperty(k),
            ...(services[k] || {}),
          };
          const expanded = this.state.expanded[k] || false;
          return (
            <Card key={k} raised={false} square>
              <ListItem button onClick={() => this.toggleExpand(k)}>
                <ListItemText primary={k} />
                {expanded ? <ExpandLess /> : <ExpandMore />}
              </ListItem>
              <Collapse in={expanded} timeout="auto">
                <ServiceForm
                  onSubmit={(values: any) => updateService(k, values)}
                  form={k}
                  schema={schema}
                  initialValues={service}
                  enableReinitialize
                />
              </Collapse>
            </Card>
          );
        })}
      </>
    );
  }
}

const mapStateToProps = (state: RootState) => ({
  schemata: getServiceSchemata(state),
  services: getServices(state),
});

const mapDispatchToProps = {
  fetchServiceSchemata,
  fetchServices,
  updateService,
};

export default connect(mapStateToProps, mapDispatchToProps)(ServiceList);
