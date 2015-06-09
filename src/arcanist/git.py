#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#


class ArcanistGit(object):
    def __init__(self, repo):
        self.repo = repo

    def guess_best_parents(self, diff):
        return []
