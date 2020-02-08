#!/usr/bin/python -tt
#
# Copyright (c) Facebook, Inc. and its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
import os
from pathlib import Path
from typing import Optional

from .repo import RepositoryBase
from .. import eden, git

# from .. import hgapi
have_hg_support = False


def find_repo(path: Path) -> Optional[RepositoryBase]:
    ceiling_dirs = [Path(os.path.sep)]
    ceiling_dirs_env = os.environ.get('GIT_CEILING_DIRECTORIES')
    if ceiling_dirs_env:
        ceiling_dirs.extend(Path(p) for p in ceiling_dirs_env.split(':'))

    initial_path = path
    path = path.resolve(strict=False)
    while True:
        repo = _try_get_repo(path)
        if repo is not None:
            return repo

        # If the parent_dir is one of the ceiling directories,
        # we should stop before examining it.
        parent_dir = path.parent
        if parent_dir in ceiling_dirs:
            return None

        path = parent_dir


def _try_get_repo(path: Path) -> Optional[RepositoryBase]:
    # Check to see if this directory contains a .git file or directory
    ret = git.check_git_path(path)
    if ret is not None:
        return git.get_repo(ret[0], ret[1])

    # Check to see if this directory looks like a git directory
    if git.is_git_dir(path):
        return git.get_repo(path)

    # Check to see if this directory contains a .hg directory
    #
    # This could be either an EdenSCM repository (EdenSCM was originally based
    # on Mercurial), or a pure Mercurial repository.
    hg_dir = os.path.join(path, '.hg')
    if os.path.isdir(hg_dir):
        try:
            with open(os.path.join(hg_dir, "requires"), "r") as f:
                requirements = f.read().splitlines()
        except EnvironmentError:
            requirements = []

        # All EdenSCM repositories generally list treestate and remotefilelog
        # in their requirements.
        if "treestate" in requirements and "remotefilelog" in requirements:
            return eden.Repository(path)

        # Otherwise assume this is a vanilla Mercurial repository
        if have_hg_support:
            return hgapi.Repository(path)
        raise Exception("this looks like a Mercurial repository, "
                        "but Mercurial support is not available")

    return None


def _resolve_commits_common(ap, args):
    # Parse the commit arguments
    if args.commit is not None:
        # If --commit was specified, diff that commit against its parent
        if args.differential is not None:
            ap.error('--commit and --differential are mutually exclusive')
        if args.cached:
            ap.error('--commit and --cached are mutually exclusive')
        if not (args.parent_commit is None and args.child_commit is None):
            ap.error('additional commit arguments may not be specified '
                     'with --commit')

        args.parent_commit = args.commit + '^'
        args.child_commit = args.commit
        return True

    if args.differential is not None:
        # If --differential was specified,
        # review that differential revision
        if args.cached:
            ap.error('--differential and --cached are mutually exclusive')
        if not (args.parent_commit is None and args.child_commit is None):
            ap.error('additional commit arguments may not be specified '
                     'with --differential')
        # We can't compute the parent and child commits now.
        # The code will not use them if it sees that args.differential is
        # set.
        return True

    return False


def _resolve_commits_git(ap, args):
    if args.cached:
        # Diff HEAD or some other parent against the index
        if args.child_commit is not None:
            ap.error('cannot specify --cached with two commits')
        args.child_commit = git.COMMIT_INDEX
        if args.parent_commit is None:
            args.parent_commit = git.COMMIT_HEAD
        return

    # If we are still here there were no special arguments.
    # Just use the parent and child arguments.
    # The child is the working directory, unless otherwise specified.
    if args.child_commit is None:
        args.child_commit = git.COMMIT_WD
    # If neither child or parent is specified, diff the working
    # directory against the index.
    if args.parent_commit is None:
        args.parent_commit = git.COMMIT_INDEX


def _resolve_commits_hg(ap, args):
    if args.cached:
        ap.error('--cached is only supported in git repositories, '
                 'not mercurial')

    if args.child_commit is None:
        args.child_commit = hgapi.COMMIT_WD
    if args.parent_commit is None:
        args.parent_commit = hgapi.COMMIT_HEAD


def resolve_commits(repo, ap, args):
    if _resolve_commits_common(ap, args):
        return

    if have_hg_support and isinstance(repo, hgapi.Repository):
        _resolve_commits_hg(ap, args)
    else:
        _resolve_commits_git(ap, args)
