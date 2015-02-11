#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from ..scm import ScmAPI


class HgAPI(ScmAPI):
    def __init__(self, repo):
        super(HgAPI, self).__init__()
        self.repo = repo

    def expand_commit_name(self, name, aliases):
        # TODO: handle aliases in more complicated patterns
        # (e.g., child^)
        if name in aliases:
            return aliases[name]
        return name
