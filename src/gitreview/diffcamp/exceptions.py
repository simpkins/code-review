#!/usr/bin/python -tt
#
# Copyright (c) 2009-present Facebook.  All rights reserved.
#
__all__ = ['DiffCampError', 'NoSuchRevisionError', 'NoDiffsError',
           'DiffcampGitError', 'NotADiffcampCommitError']


class DiffCampError(Exception):
    pass


class NoSuchRevisionError(DiffCampError):
    def __init__(self, rev_id):
        DiffCampError.__init__(self)
        self.revisionId = rev_id

    def __str__(self):
        return 'no such revision %s' % (self.revisionId,)


class NoDiffsError(DiffCampError):
    def __init__(self, rev_id):
        DiffCampError.__init__(self)
        self.revisionId = rev_id

    def __str__(self):
        return 'revision %s has no diffs' % (self.revisionId,)


class DiffcampGitError(DiffCampError):
    pass


class NotADiffcampCommitError(DiffcampGitError):
    def __init__(self, commit, reason):
        DiffcampGitError.__init__(self)
        self.commit = commit
        self.reason = reason

    def __str__(self):
        return ('%.7s is not a DiffCamp commit: %s' %
                (self.commit.sha1, self.reason))
