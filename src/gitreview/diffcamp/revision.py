#!/usr/bin/python -tt
#
# Copyright (c) 2010- Facebook.  All rights reserved.
#
import httplib
import json

import constants
from exceptions import *


def _make_http_request(path):
    conn = httplib.HTTPConnection(constants.SERVER)
    conn.request('GET', path)
    r = conn.getresponse()
    body = r.read()

    return (r.status, r.reason, body)


class Diff(object):
    def __init__(self, revision, dict):
        params = ['id', 'dateCreated', 'dateModified', 'revisionID',
                  'originalText', 'lines', 'parsedCommitMessage',
                  'sourceControlSystem', 'sourceMachine', 'sourcePath',
                  'checksum', 'sourceControlBaseRevision', 'autoProcessed',
                  'requireRTLTest', 'sourceControlPath']
        for param in params:
            if dict.has_key(param):
                setattr(self, param, dict[param])
            else:
                setattr(self, param, None)

        self.revision = revision

    def getPatch(self):
        path = '/intern/diffcamp/patch.php?id=%d' % (self.id,)
        (status, reason, body) = _make_http_request(path)
        if status != 200:
            raise Exception('failed to get patch for diff %s: %s %s' %
                            (self.id, status, reason))
        return body


class Revision(object):
    def __init__(self, dict):
        params = ['id', 'status', 'ownerID', 'name', 'ownerName',
                  'dateCreated', 'dateModified', 'summary', 'notes',
                  'testPlan', 'revert', 'bugId', 'tracTicketID', 'projectID',
                  'lines', 'lastActorID', 'svnRevision',
                  'repositoryID', 'dateCommitted', 'svnBlameRevision',
                  'bugzillaID', 'platformImpact', 'mobileImpact', 'perfImpact',
                  'gitRevision', 'fbid', 'diffs']

        for param in params:
            if dict.has_key(param):
                setattr(self, param, dict[param])
            else:
                setattr(self, param, None)

        orig_diffs = self.diffs
        self.diffs = []
        if orig_diffs:
            for diff_dict in orig_diffs.itervalues():
                diff = Diff(self, diff_dict)
                self.diffs.append(diff)
            # Sort the diffs in ascending order by ID.
            self.diffs.sort(key = lambda d: d.id)

    def getActiveDiff(self):
        if not self.diffs:
            raise Exception('revision %s has no diffs' % (self.id,))
        # The last diff is the currently active one.
        return self.diffs[-1]

    def getPatch(self):
        return self.getActiveDiff().getPatch()

    def getCommitMessage(self):
        if self.name:
            msg = self.name + '\n'
        else:
            msg = 'DiffCamp Revision: %s\n' % (self.id,)

        if self.summary:
            msg += '\nSummary:\n' + self.summary + '\n'
        if self.testPlan:
            msg += '\nTest Plan:\n' + self.testPlan + '\n'
        if self.revert:
            msg += '\nRevert Plan:\n' + self.revert + '\n'
        if self.notes:
            msg += '\nOther Notes:\n' + self.notes + '\n'
        # TODO: we could also use platformImpact, perfImpact,
        # mobileImpact, etc.

        msg += '\nDiffCamp Revision: %s\n' % (self.id,)

        return msg


def get_revision(rev_id):
    path = '/intern/diffcamp/json.php?revisionID=%d' % (rev_id,)
    (status, reason, body) = _make_http_request(path)
    if status != 200:
        if status == 400 and reason.find('No such revision') >= 0:
            raise NoSuchRevisionError(rev_id)
        raise Exception('failed to get information for revision %s: %s %s' %
                        (rev_id, status, reason))

    dict = json.loads(body)
    return Revision(dict)
