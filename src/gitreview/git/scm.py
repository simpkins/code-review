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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return
