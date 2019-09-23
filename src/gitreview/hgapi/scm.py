#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from ..scm import ScmAPI
from .constants import COMMIT_WD, COMMIT_WD_STR, WorkingDirectoryCommit

try:
    import edenscm.mercurial as mercurial
    import edenscm.mercurial.scmutil
except ImportError:
    import mercurial.scmutil


class HgAPI(ScmAPI):
    def __init__(self, repo):
        super(HgAPI, self).__init__()
        self.repo = repo

    def __enter__(self):
        self.repo.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.repo.__exit__(exc_type, exc_value, traceback)
        return
