#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from ..scm import ScmAPI

import mercurial.scmutil


class HgAPI(ScmAPI):
    def __init__(self, repo):
        super(HgAPI, self).__init__()
        self.repo = repo

    def expand_commit_name(self, name, aliases):
        try:
            # Use our custom UI object to define our aliases
            # while we perform the expansion.
            self.repo.repo.ui._gitreview_aliases = aliases
            rev = mercurial.scmutil.revsingle(self.repo.repo, name)
            return rev.hex()
        except Exception as ex:
            raise
            #return name
        finally:
            self.repo.repo.ui._gitreview_aliases = {}
