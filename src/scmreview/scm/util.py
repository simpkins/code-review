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
import scmreview.git.repo


def find_repo(path: Path) -> Optional[RepositoryBase]:
    ceiling_dirs = [Path(os.path.sep)]
    ceiling_dirs_env = os.environ.get("GIT_CEILING_DIRECTORIES")
    if ceiling_dirs_env:
        ceiling_dirs.extend(Path(p) for p in ceiling_dirs_env.split(":"))

    initial_path = path
    path = path.resolve(strict=False)
    while True:
        repo = _try_get_repo(path)
        if repo is not None:
            return repo

        # If the parent_dir is one of the ceiling directories,
        # we should stop before examining it.
        parent_dir = path.parent
        if parent_dir in ceiling_dirs or parent_dir == path:
            return None

        path = parent_dir


def _try_get_repo(path: Path) -> Optional[RepositoryBase]:
    # Check to see if this directory contains a .git file or directory
    git_repo = git.check_git_path(path)
    if git_repo is not None:
        return git_repo

    # Check to see if this directory looks like a git directory
    if git.is_git_dir(path):
        return git.get_repo(path)

    # Check to see if this directory contains a .hg directory
    #
    # This could be either an EdenSCM repository (EdenSCM was originally based
    # on Mercurial), or a pure Mercurial repository.
    hg_dir = os.path.join(path, ".hg")
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
        # TODO: Implement vanilla Mercurial support again.
        raise Exception(
            "this looks like a Mercurial repository, "
            "but Mercurial support is not available"
        )

    return None
