#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from .conduit import ArcanistConduitClient
from .err import ConduitClientError, PatchFailedError
from .working_copy import WorkingCopy
from . import revision
from . import hg as arc_hg
from . import git as arc_git

from gitreview import hgapi

import os
import logging
import pprint


def apply_diffs(repo, rev_id):
    return _Applier(repo, rev_id).run()


class CommitInfo(object):
    def __init__(self, author_name, author_email, timestamp, message, prev):
        self.author_name = author_name
        self.author_email = author_email
        self.timestamp = timestamp
        self.message = message
        self.prev_commit = prev


class _Applier(object):
    def __init__(self, repo, rev_id):
        self.conduit = None
        self.rev = None
        self._commit_msg = None

        self.repo = repo
        self.rev_id = rev_id
        self.arc_dir = WorkingCopy(os.getcwd())
        if isinstance(repo, hgapi.Repository):
            self.arc_scm = arc_hg.ArcanistHg(repo, self.arc_dir)
        else:
            self.arc_scm = arc_git.ArcanistGit(repo, self.arc_dir)

    def run(self):
        self.conduit = ArcanistConduitClient(self.arc_dir)
        self.conduit.connect()
        self.rev = revision.get_revision(self.conduit, self.rev_id)

        existing = self.arc_scm.find_diff_commits(self.rev)

        # If a previous run skipped some early diffs, and applied later ones,
        # only start processing after the diffs that were already applied.
        # Don't bother trying to apply earlier diffs that we already
        # tried and failed to apply before.
        # If we have already app
        results = []
        to_apply = []
        for diff_idx, diff in enumerate(self.rev.diffs):
            commit = existing.get(diff.id)
            if commit is None:
                to_apply.append((diff_idx, diff))
            else:
                logging.debug('Diff %s already applied as %s', diff.id, commit)
                results.append(commit)
                to_apply = []

        for diff_idx, diff in to_apply:
            if results:
                prev_commit = results[-1]
            else:
                prev_commit = None
            info = self._get_commit_info(diff, prev_commit)
            try:
                commit = self.arc_scm.apply_diff(diff, self.rev, info)
                results.append(commit)
            except PatchFailedError as ex:
                # We always need to apply the current diff (the last one in the
                # list) in order for review.
                if diff_idx + 1 == len(self.rev.diffs):
                    raise

                # However, for previous diffs that aren't the current one, just
                # continue trying to apply later diffs, rather than completely
                # failing here.
                logging.error('Failed to find a changeset where diff %s (%s) '
                              'applies. Ignoring it, and continuing anyway',
                              diff_idx + 1, diff.id)
                continue

        return results

    def _get_commit_info(self, diff, parent_commit):
        if self._commit_msg is None:
            self._commit_msg = self._get_commit_msg()
        return CommitInfo(author_name=diff.all_params['authorName'],
                          author_email=diff.all_params['authorEmail'],
                          timestamp=diff.all_params['dateCreated'],
                          message=self._commit_msg,
                          prev=parent_commit)

    def _get_commit_msg(self):
        relevant_phids = [self.rev.author_phid] + self.rev.reviewer_phids
        phid_map = self.conduit.call_method('phid.query', phids=relevant_phids)

        def get_phid_name(phid):
            info = phid_map[phid]
            phid_type = info['typeName']
            if phid_type == 'Phabricator User':
                return info['name']
            elif info['typeName'] == 'Project':
                return '#' + info['name']
            raise Exception('unknown PHID type for %r: %r' % (phid, info))

        reviewer_names = ', '.join(get_phid_name(phid)
                                   for phid in self.rev.reviewer_phids)
        template = '''\
{title}

Summary:
{summary}

Test Plan:
{test_plan}

Reviewers: {reviewers}

Differential Revision: {uri}
'''
        return template.format(title=self.rev.title,
                               summary=self.rev.summary,
                               test_plan=self.rev.test_plan,
                               reviewers=reviewer_names,
                               uri=self.rev.uri)


def _dump_changes(diff):
    #_dump_diff(diff)
    for change in diff.changes:
        print('-' * 60)

        _dump_change(change)
        continue

        if change.old_path != change.current_path:
            print('%s --> %s' % (change.old_path, change.current_path))
        else:
            print(change.current_path)
        print('%d hunks:' % len(change.hunks))
        for hunk in change.hunks:
            # corpus contains a unified diff, with a very large amount of
            # context.
            for k in sorted(hunk.keys()):
                v = hunk[k]
                print('  %s: %s' % (k, v))
        #print(diff.get_patch())
        #print(diff.get_patch())
    print('=' * 60)
    return

def _dump_diff(diff):
    diff.all_params['changes'] = None
    diff.all_params['properties']['arc:unit'] = None
    diff.all_params['properties']['facebook:contbuild'] = None
    diff.all_params['properties']['facebook:sc_async'] = None

    pprint.pprint(vars(diff), indent=2)

def _dump_change(change):
    pprint.pprint(vars(change), indent=2)
