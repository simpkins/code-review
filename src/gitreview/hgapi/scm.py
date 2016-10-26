#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from ..scm import ScmAPI
from .constants import COMMIT_WD, COMMIT_WD_STR, WorkingDirectoryCommit

import mercurial.scmutil


class HgAPI(ScmAPI):
    def __init__(self, repo):
        super(HgAPI, self).__init__()
        self.repo = repo

    def expand_commit_name(self, name, aliases):
        # COMMIT_WD isn't a string, and points to fake WorkingDirectoryCommit
        # objects.  We have to handle it specially, and make sure we don't
        # pass the WorkingDirectoryCommit objects down to mercurial code.
        if name == COMMIT_WD or name == COMMIT_WD_STR:
            return COMMIT_WD
        # Do an explicit lookup in aliases first, to handle aliases
        # which point to a WorkingDirectoryCommit object.  We don't allow
        # these aliases to be used in more complicated revset expressions,
        # since these expressions don't make sense.
        ret = aliases.get(name)
        if ret is not None:
            return ret

        real_aliases = dict((n, v)
                            for n, v in aliases.items()
                            if not isinstance(v, WorkingDirectoryCommit))

        try:
            # Use our custom UI object to define our aliases
            # while we perform the expansion.
            self.repo.repo.ui._gitreview_aliases = real_aliases
            rev = mercurial.scmutil.revsingle(self.repo.repo, name)
            return rev.hex()
        except Exception as ex:
            raise
            #return name
        finally:
            self.repo.repo.ui._gitreview_aliases = {}
