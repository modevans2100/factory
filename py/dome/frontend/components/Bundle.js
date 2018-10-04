// Copyright 2016 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import ChosenIcon from 'material-ui/svg-icons/toggle/star';
import DeleteIcon from 'material-ui/svg-icons/action/delete';
import DragHandleIcon from 'material-ui/svg-icons/editor/drag-handle';
import UnchosenIcon from 'material-ui/svg-icons/toggle/star-border';
import IconButton from 'material-ui/IconButton';
import Immutable from 'immutable';
import React from 'react';
import Toggle from 'material-ui/Toggle';
import {connect} from 'react-redux';
import {Card, CardHeader, CardTitle, CardText} from 'material-ui/Card';
import {SortableHandle} from 'react-sortable-hoc';

import BundlesActions from '../actions/bundlesactions';
import DomeActions from '../actions/domeactions';
import ResourceTable from './ResourceTable';
import RuleTable from './RuleTable';

var DragHandle = SortableHandle(() => (
  <IconButton
    tooltip='move this bundle'
    style={{cursor: 'move'}}
    onClick={e => e.stopPropagation()}
  >
    <DragHandleIcon />
  </IconButton>
));

var Bundle = React.createClass({
  propTypes: {
    activateBundle: React.PropTypes.func.isRequired,
    changeBundleRules: React.PropTypes.func.isRequired,
    deleteBundle: React.PropTypes.func.isRequired,
    bundle: React.PropTypes.instanceOf(Immutable.Map).isRequired,
    projectName: React.PropTypes.string.isRequired,
    projectNetbootBundle: React.PropTypes.string.isRequired,
    setAsNetboot: React.PropTypes.func.isRequired,
    expanded: React.PropTypes.bool.isRequired,
    expandBundle: React.PropTypes.func.isRequired,
    collapseBundle: React.PropTypes.func.isRequired,
  },

  handleActivate(event) {
    event.stopPropagation();
    const {bundle} = this.props;
    this.props.activateBundle(bundle.get('name'), !bundle.get('active'));
  },

  toggleExpand() {
    if (this.props.expanded) {
      this.props.collapseBundle(this.props.bundle.get('name'));
    } else {
      this.props.expandBundle(this.props.bundle.get('name'));
    }
  },

  render() {
    const {
      bundle,
      expanded,
      projectName,
      projectNetbootBundle,
      deleteBundle,
      setAsNetboot
    } = this.props;

    const INACTIVE_STYLE = {
      opacity: 0.3
    };

    return (
      <Card
        className='bundle'
        expanded={expanded}
        containerStyle={bundle.get('active') ? {} : INACTIVE_STYLE}
      >
        <CardTitle
          title={bundle.get('name')}
          subtitle={bundle.get('note')}
          // Cannot use actAsExpander here, need to implement ourselves. The
          // Toggle below from Material-UI somewhat would not capture the click
          // event before CardTitle. If not using this way, when the user clicks
          // on the Toggle (which should only change the state of the Toggle),
          // the Card will also be affected (expanded or collapsed).
          onClick={this.toggleExpand}
          style={{cursor: 'pointer'}}
        >
          {/* TODO(littlecvr): top and right should be calculated */}
          <div style={{position: 'absolute', top: 18, right: 18}}>
            <div
              style={{display: 'inline-block'}}
              onClick={this.handleActivate}
            >
              <Toggle
                label={bundle.get('active') ? 'ACTIVE' : 'INACTIVE'}
                toggled={bundle.get('active')}
              />
            </div>
            {/* make some space */}
            <div style={{display: 'inline-block', width: 48}}></div>
            <DragHandle />
            <IconButton
              tooltip='delete this bundle'
              onClick={e => e.stopPropagation()}
              onTouchTap={() => deleteBundle(bundle.get('name'))}
            >
              <DeleteIcon />
            </IconButton>
            <IconButton
              tooltip="use this bundle's netboot resource"
              onClick={e => e.stopPropagation()}
              onTouchTap={() => setAsNetboot(bundle.get('name'), projectName)}
            >
              {(projectNetbootBundle == bundle.get('name')) &&
                <ChosenIcon />}
              {!(projectNetbootBundle == bundle.get('name')) &&
                <UnchosenIcon />}
            </IconButton>
          </div>
        </CardTitle>
        <CardHeader title='RESOURCES' expandable={true} />
        <CardText expandable={true}>
          <ResourceTable bundle={bundle} />
        </CardText>
        <CardHeader title='RULES' expandable={true} />
        <CardText expandable={true}>
          <RuleTable
            rules={bundle.get('rules')}
            changeRules={
              rules => this.props.changeBundleRules(bundle.get('name'), rules)
            }
          />
        </CardText>
      </Card>
    );
  }
});

function mapStateToProps(state, ownProps) {
  return {
    expanded: state.getIn([
      'bundles',
      'expanded',
      ownProps.bundle.get('name')
    ]),
    projectName: state.getIn(['dome', 'currentProject']),
    projectNetbootBundle: state.getIn([
      'dome',
      'projects',
      state.getIn(['dome', 'currentProject']),
      'netbootBundle'
    ])
  };
}

function mapDispatchToProps(dispatch) {
  return {
    activateBundle: (name, active) =>
        dispatch(BundlesActions.activateBundle(name, active)),
    changeBundleRules: (name, rules) =>
        dispatch(BundlesActions.changeBundleRules(name, rules)),
    deleteBundle: name => dispatch(BundlesActions.deleteBundle(name)),
    setAsNetboot: (name, projectName)  =>
        dispatch(DomeActions.updateProject(
            projectName, {'netbootBundle': name, 'umpireEnabled': true})),
    expandBundle: name => dispatch(BundlesActions.expandBundle(name)),
    collapseBundle: name => dispatch(BundlesActions.collapseBundle(name))
  };
}

export default connect(mapStateToProps, mapDispatchToProps)(Bundle);