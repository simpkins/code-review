#!/usr/bin/python3 -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from __future__ import absolute_import, division, print_function

import os
import sys

from .. import git
have_git_support = True

if sys.version_info[0] >= 3:
    from .. import eden
    have_eden_support = True
else:
    have_eden_support = False

try:
    from .. import hgapi
    have_hg_support = True
except ImportError:
    have_hg_support = False


def find_repo(ap, args):
    if args.git_dir is not None or args.work_tree is not None:
        if args.hg_repo is not None:
            ap.error('Cannot specify both a mercurial and a git repository')
        if not have_git_support:
            ap.error('support for Git repositories is not available')
        return git.get_repo(git_dir=args.git_dir, working_dir=args.work_tree)

    if args.hg_repo is not None:
        if not have_hg_support is not None:
            ap.error('support for Mercurial repositories is not available')
        return hgapi.Repository(args.hg_repo)

    # Search upwards for a mercurial or a git repository
    cwd = os.getcwd()
    return search_for_repo(cwd)


def search_for_repo(path):
    ceiling_dirs = []
    ceiling_dirs_env = os.environ.get('GIT_CEILING_DIRECTORIES')
    if ceiling_dirs_env:
        ceiling_dirs = ceiling_dirs_env.split(':')
    ceiling_dirs.append(os.path.sep) # Add the root directory

    initial_path = path
    path = os.path.normpath(path)
    while True:
        repo = _try_get_repo(path)
        if repo is not None:
            return repo

        # If the parent_dir is one of the ceiling directories,
        # we should stop before examining it.
        parent_dir = os.path.dirname(path)
        if parent_dir in ceiling_dirs:
            raise git.NotARepoError(initial_path)

        path = parent_dir


def _try_get_repo(path):
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
        if have_eden_support:
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
