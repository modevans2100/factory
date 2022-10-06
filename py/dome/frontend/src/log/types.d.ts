// Copyright 2019 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

export type ComponentState =
  'SUCCEEDED' |
  'WAITING' |
  'PROCESSING' |
  'FAILED' |
  'REPORT';

export type ComponentType =
  'header' |
  'item' |
  'list-item';

export interface LogFormData {
  logType: string;
  archiveSize: number;
  archiveUnit: string;
  startDate: string;
  endDate: string;
  actionType: string;
}

export interface Pile {
  title: string;
  tempDir: string;
  projectName: string;
  compressState: ComponentState;
  compressReports: string[];
  cleanupState: ComponentState;
  cleanupReports: string[];
  downloadStateMap: DownloadStateMap;
  actionType: string;
}

export interface ExpansionMap {
  [key: string]: boolean;
}

export interface PileMap {
  [key: string]: Pile;
}

export interface DownloadStateMap {
  [logfile: string]: ComponentState;
}
