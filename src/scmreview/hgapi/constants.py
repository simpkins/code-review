#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#

COMMIT_WD_STR = ':wd'

class WorkingDirectoryCommit():
    def __str__(self):
        return COMMIT_WD_STR


COMMIT_WD = WorkingDirectoryCommit()
COMMIT_HEAD = '.'
