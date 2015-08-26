#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#

class WorkingDirectoryCommit():
    def __str__(self):
        return ':wd'


COMMIT_WD = WorkingDirectoryCommit()
COMMIT_HEAD = '.'
