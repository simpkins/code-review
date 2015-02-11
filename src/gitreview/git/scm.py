#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from ..scm import ScmAPI
from .commit import split_rev_name


class GitAPI(ScmAPI):
    def __init__(self, repo):
        super(GitAPI, self).__init__()
        self.repo = repo

    def expand_commit_name(self, name, aliases):
        # Split apart the commit name from any suffix
        commit_name, suffix = split_rev_name(name)

        try:
            real_commit = aliases[commit_name]
        except KeyError:
            real_commit = commit_name

        return real_commit + suffix
