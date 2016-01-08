#!/usr/bin/python3 -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
import os

from .. import git
from .. import hgapi
from ..git.scm import GitAPI
from ..hgapi.scm import HgAPI


def find_repo(path):
    ceiling_dirs = []
    if os.environ.has_key('GIT_CEILING_DIRECTORIES'):
        ceiling_dirs = os.environ['GIT_CEILING_DIRECTORIES'].split(':')
    ceiling_dirs.append(os.path.sep) # Add the root directory

    initial_path = path
    path = os.path.normpath(path)
    while True:
        # Check to see if this directory contains a .git file or directory
        ret = git.check_git_path(path)
        if ret is not None:
            return GitAPI(git.get_repo(ret[0], ret[1]))

        # Check to see if this directory contains a .hg directory
        if hgapi.is_hg_repo(path):
            return HgAPI(hgapi.Repository(path))

        # Check to see if this directory looks like a git directory
        if git.is_git_dir(path):
            return GitAPI(git.get_repo(path))

        # If the parent_dir is one of the ceiling directories,
        # we should stop before examining it.  The current directory
        # does not appear to be inside a git repository.
        parent_dir = os.path.dirname(path)
        if parent_dir in ceiling_dirs:
            raise git.NotARepoError(initial_path)

        path = parent_dir
