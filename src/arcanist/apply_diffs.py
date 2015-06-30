#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from . conduit import ArcanistConduitClient
from .err import ConduitClientError
from . import revision
from . import hg as arc_hg
from . import git as arc_git

from gitreview import hgapi

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
        if isinstance(repo, hgapi.Repository):
            self.arc_scm = arc_hg.ArcanistHg(repo)
        else:
            self.arc_scm = arc_git.ArcanistGit(repo)

    def run(self):
        self.conduit = ArcanistConduitClient(self.repo.workingDir)
        self.conduit.connect()
        self.rev = revision.get_revision(self.conduit, self.rev_id)

        existing = self.arc_scm.find_diff_commits(self.rev)

        results = []
        for diff in self.rev.diffs:
            commit = existing.get(diff.id)
            if commit is not None:
                logging.debug('Diff %s already applied as %s',
                              diff.id, commit)
                results.append(commit)
                continue

            if results:
                prev_commit = results[-1]
            else:
                prev_commit = None
            info = self._get_commit_info(diff, prev_commit)
            commit = self.arc_scm.apply_diff(diff, self.rev, info)
            results.append(commit)

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
        user_phids = [self.rev.author_phid] + self.rev.reviewer_phids
        users = self.conduit.call_method('user.query', phids=user_phids)
        user_map = dict((u['phid'], u) for u in users)

        reviewer_names = ', '.join(user_map[phid]['userName']
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
