#!/usr/bin/python -tt
#
# Copyright 2009-2010 Facebook, Inc.
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
"""
This is a python package for interacting with git repositories.
"""

from __future__ import absolute_import, division, print_function

import errno
import os
import re
import stat

# Import all of the constants and exception types into the current namespace
from .constants import *
from .exceptions import *

from . import obj
from . import commit
from . import config
from . import diff
from . import repo


def is_git_dir(path):
    """
    is_git_dir(path) --> bool

    Determine if the specified directory is the root of a git repository
    directory.
    """
    # Check to see if the object directory exists.
    # This is normally a directory called "objects" inside the git directory,
    # but it can be overridden with the GIT_OBJECT_DIRECTORY environment
    # variable.
    object_dir = os.environ.get('GIT_OBJECT_DIRECTORY')
    if object_dir is None:
        object_dir = os.path.join(path, 'objects')
    if not os.path.isdir(object_dir):
        return False

    # Check for the refs directory
    if not os.path.isdir(os.path.join(path, 'refs')):
        return False

    # Check for the HEAD file
    # TODO: git also verifies that HEAD looks valid.
    if not os.path.exists(os.path.join(path, 'HEAD')):
        return False

    return True


def _get_git_dir(git_dir=None, cwd=None):
    """
    _get_git_dir(git_dir=None, cwd=None) --> (git_dir, working_dir)

    Attempt to find the git directory, similarly to the way git does.
    git_dir should be the git directory explicitly specified on the command
    line, or None if not explicitly specified.

    If git_dir is not explicitly specified, the GIT_DIR environment variable
    will be checked.  If that is not specified, the current working directory
    and its parent directories will be searched for a git directory.

    Returns a tuple containing the git directory, and the default working
    directory.  (The default working directory is only to be used if the
    repository is not bare, and the working directory was not specified
    explicitly via some other mechanism.)  The default working directory
    may be None if there is no default working directory.
    """
    if cwd is None:
        cwd = os.getcwd()

    # If git_dir wasn't explicitly specified, but GIT_DIR is set in the
    # environment, use that.
    if git_dir == None and os.environ.has_key('GIT_DIR'):
        git_dir = os.environ['GIT_DIR']

    # If the git directory was explicitly specified, use that.
    # The default working directory is the current working directory
    if git_dir != None:
        if not is_git_dir(git_dir):
            raise NotARepoError(git_dir)
        return (git_dir, cwd)

    # Otherwise, attempt to find the git directory by searching up from
    # the current working directory.
    ceiling_dirs = []
    if os.environ.has_key('GIT_CEILING_DIRECTORIES'):
        ceiling_dirs = os.environ['GIT_CEILING_DIRECTORIES'].split(':')
    ceiling_dirs.append(os.path.sep) # Add the root directory

    path = os.path.normpath(cwd)
    while True:
        # Check to see if this directory contains a .git file or directory
        ret = check_git_path(path)
        if ret is not None:
            return ret

        # Check to see if this directory looks like a git directory
        if is_git_dir(path):
            return (path, None)

        # Walk up to the parent directory before looping again
        (parent_dir, rest) = os.path.split(path)

        # If the parent_dir is one of the ceiling directories,
        # we should stop before examining it.  The current directory
        # does not appear to be inside a git repository.
        if parent_dir in ceiling_dirs:
            raise NotARepoError(cwd)

        path = parent_dir


def check_git_path(path):
    git_path = os.path.join(path, '.git')
    try:
        stat_info = os.lstat(git_path)
    except OSError as ex:
        if ex.errno == errno.ENOENT:
            return None
        raise

    if stat.S_ISREG(stat_info.st_mode):
        # Submodules contain .git files that point to their git directory
        # location.  The file contains a single line of the format
        # "gitdir: <path>"
        with open(git_path) as f:
            first_line = f.readline()
        m = re.match(r'^gitdir: (.*)\n?', first_line)
        if m:
            dest = os.path.normpath(os.path.join(path, m.group(1)))
            if not is_git_dir(dest):
                raise GitError('%s points to bad git diretory %s' %
                               (git_path, dest))
            return (dest, path)
    elif stat.S_ISDIR(stat_info.st_mode):
        if is_git_dir(git_path):
            return (git_path, path)

    return None


def get_repo(git_dir=None, working_dir=None):
    """
    get_repo(git_dir=None) --> Repository object

    Create a Repository object.  The repository is found similarly to the way
    git itself works:
    - If git_dir is specified, that is used as the git directory
    - Otherwise, if the GIT_DIR environment variable is set, that is used as
      the git directory
    - Otherwise, the current working directory and its parents are searched to
      find the git directory
    """
    # Find the git directory and the default working directory
    (git_dir, default_working_dir) = _get_git_dir(git_dir)

    # Load the git configuration for this repository
    git_config = config.load(git_dir)

    # If working_dir wasn't explicitly specified, but GIT_WORK_TREE is set in
    # the environment, use that.
    if working_dir == None and os.environ.has_key('GIT_WORK_TREE'):
        working_dir = os.environ['GIT_WORK_TREE']

    if working_dir == None:
        is_bare = git_config.getBool('core.bare', False)
        if is_bare:
            working_dir = None
        else:
            working_dir = git_config.get('core.worktree', None)
            if working_dir is None:
                working_dir = default_working_dir
            else:
                working_dir = os.path.join(git_dir, working_dir)
                working_dir = os.path.normpath(working_dir)

    return repo.Repository(git_dir, working_dir, git_config)
