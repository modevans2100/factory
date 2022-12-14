#!/usr/bin/env python3
#
# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Print the status of factory-related repositories.

This is used to generate the file containing the status of each repositories
in the factory toolkit.
"""

import argparse
import os

from cros.factory.utils.cros_board_utils import BuildBoard
from cros.factory.utils.process_utils import CheckOutput


NUM_COMMITS_PER_REPO = 50

SRC = os.path.join(os.environ['CROS_WORKON_SRCROOT'], 'src')
MERGED_MSG = ['Reviewed-on', 'Marking set of ebuilds as stable']


def GitLog(repo, skip=0, max_count=NUM_COMMITS_PER_REPO, extra_args=None):
  cmd = [
      'git', 'log', '--max-count', f'{int(max_count)}', '--skip', f'{int(skip)}'
  ]
  if extra_args:
    cmd.extend(extra_args)
  return CheckOutput(cmd, cwd=repo).strip()


def GetCommitList(repo, skip=0, max_count=NUM_COMMITS_PER_REPO):
  if not max_count:
    return []
  return GitLog(repo, skip=skip, max_count=max_count,
                extra_args=['--oneline']).split('\n')


def GetUncommittedFiles(repo):
  files = CheckOutput(['git', 'status', '--porcelain'], cwd=repo)
  if not files:
    return []
  return files.strip().split('\n')


def GetUnmergedCommits(repo):
  for idx in range(NUM_COMMITS_PER_REPO):
    commit_log = GitLog(repo, skip=idx, max_count=1)
    for msg in MERGED_MSG:
      if msg in commit_log:
        return GetCommitList(repo, skip=0, max_count=idx)
  return GetCommitList(repo, skip=0, max_count=NUM_COMMITS_PER_REPO)


def main():
  parser = argparse.ArgumentParser(
      description='Prints the status of factory-related repositories.')
  parser.add_argument('--board', '-b', required=True,
                      help='The board to check overlay repositories for.')
  args = parser.parse_args()

  repos = ['platform/factory', BuildBoard(args.board).factory_board_files]
  for repo_path in repos:
    if not repo_path:
      raise ValueError(
          f'No overlay available for {args.board}! Please check if the board is'
          f' correct and you have done `setup_board --board {args.board}`.')
    print(f'Repository {repo_path}')
    repo_full_path = os.path.join(SRC, repo_path)

    if not os.path.exists(repo_full_path):
      print('  >>> Repository does not exist')
      continue

    uncommitted = GetUncommittedFiles(repo_full_path)
    if uncommitted:
      print('  >>> Repository contains uncommitted changes:')
      for changed_file in uncommitted:
        print(f'\t{changed_file}')

    unmerged = GetUnmergedCommits(repo_full_path)
    if unmerged:
      print(f'  >>> Repository contains {len(unmerged)} unmerged commits:')
      for commit in unmerged:
        print(f'\t{commit}')

    commit_list = GetCommitList(repo_full_path)
    print(f'  >>> Last {len(commit_list)} commits in the repository:')
    for commit in commit_list:
      print(f'\t{commit}')

    print('\n')


if __name__ == '__main__':
  main()
