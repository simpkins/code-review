#!/usr/local/bin/python2.6 -tt
#
# Copyright 2004-present Facebook.  All rights reserved.
#
import subprocess

from . conduit import ArcanistConduitClient
from .err import *


def _populate_json_object(object, params, mapping):
    for key, attr_name in mapping.iteritems():
        if not attr_name:
            attr_name = key
        if params.has_key(key):
            setattr(object, attr_name, params[key])
        else:
            setattr(object, attr_name, None)


class ChangeSet(object):
    def __init__(self, diff, params):
        self.diff = diff
        self.all_params = params

        mapping = {
            'currentPath': 'current_path',
            'oldPath': 'old_path',
            'awayPaths': 'away_paths',
            'type': 'type',
            'commitHash': 'commit_hash',
            'oldProperties': 'old_properties',
            'newProperties': 'new_properties',
            'fileType': 'file_type',
            'hunks': None,
            'metadata': None,
        }
        _populate_json_object(self, params, mapping)


class Diff(object):
    def __init__(self, revision, params):
        self.revision = revision
        self.all_params = params
        mapping = {
            'id': None,
            'parent': None,
            'sourceControlBaseRevision': 'src_control_base_rev',
            'sourceControlPath': 'src_control_path',
        }
        _populate_json_object(self, params, mapping)

        self.changes = [ChangeSet(self, change)
                        for change in params['changes']]

    def get_patch(self):
        # TODO: it would be nice to be able to compute this on our own,
        # without having to call "arc export".
        cmd = ['arc', 'export', '--diff', str(self.id), '--git']
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (out, err) = p.communicate()
        if p.returncode != 0:
            cmd_str = ' '.join(arg in cmd)
            raise ArcanistError('error running "%s": %s' % (cmd_str, err))
        return out


class Revision(object):
    def __init__(self, params):
        self.all_params = params
        mapping = {
            'id': None,
            'phid': None,
            'uri': None,
            'status': None,
            'statusName': 'status_name',
            'authorPHID': 'author_phid',
            'reviewerPHIDs': 'reviewer_phids',
            'lineCount': 'line_count',
            'title': None,
            'summary': None,
            'testPlan': 'test_plan',
            'blameRevision': 'blame_revision',
            'revertPlan': 'revert_plan',
            'commits': None,
            'diffs': None,
            #'dateCommitted': 'date_committed',
        }
        _populate_json_object(self, params, mapping)

        orig_diffs = self.diffs
        self.diffs = []
        if orig_diffs:
            # Older versions of phabricator returned rev.diffs as a list of
            # objects, newer versions return it as a dictionary of
            # id --> object.  Convert the older list format to a dictionary if
            # necessary.
            if isinstance(orig_diffs, list):
                orig_diffs = params((diff.id, diff) for diff in orig_diffs)
            for diff_id, diff_dict in orig_diffs.iteritems():
                diff = Diff(self, diff_dict)
                self.diffs.append(diff)
            # Sort the diffs in ascending order by ID.
            self.diffs.sort(key = lambda d: d.id)

    def get_active_diff(self):
        if not self.diffs:
            raise Exception('revision %s has no diffs' % (self.id,))
        # The last diff is the currently active one.
        return self.diffs[-1]

    def get_patch(self):
        return self.get_active_diff().get_patch()

    def get_commit_message(self):
        if self.title:
            msg = self.title + '\n'
        else:
            msg = 'Differential Revision: %s\n' % (self.id,)

        if self.summary:
            msg += '\nSummary:\n' + self.summary + '\n'
        if self.test_plan:
            msg += '\nTest Plan:\n' + self.test_plan + '\n'
        if self.revert_plan:
            msg += '\nRevert Plan:\n' + self.revert_plan + '\n'
        if self.blame_revision:
            msg += '\nBlame Rev: ' + self.blame_revision + '\n'
        # TODO: we could also use platformImpact, perfImpact,
        # mobileImpact, etc.

        msg += '\nDifferential Revision: %s\n' % (self.id,)

        return msg


def get_revision(repo, rev_id):
    conduit = ArcanistConduitClient(repo)
    conduit.connect()
    try:
        revision = conduit.call_method('differential.getrevision',
                                       revision_id=rev_id)
    except ConduitClientError as ex:
        # Translate ERR_BAD_REVISION to a NoSuchRevisionError with the correct
        # revision ID stored internally
        if ex.code == 'ERR_BAD_REVISION':
            raise NoSuchRevisionError(rev_id)
        raise

    return Revision(revision)
