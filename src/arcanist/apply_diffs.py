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

import pprint


class CommitInfo(object):
    def __init__(self, author_name, author_email, timestamp, message, prev):
        self.author_name = author_name
        self.author_email = author_email
        self.timestamp = timestamp
        self.message = message
        self.prev_commit = prev


def apply_diffs(repo, rev_id):
    conduit = ArcanistConduitClient(repo.workingDir)
    conduit.connect()

    rev = revision.get_revision(conduit, rev_id)
    if isinstance(repo, hgapi.Repository):
        arc_scm = arc_hg.ArcanistHg(repo)
    else:
        arc_scm = arc_hg.ArcanistGit(repo)

    try:
        user_phids = [rev.author_phid] + rev.reviewer_phids
        users = conduit.call_method('user.query', phids=user_phids)
        user_map = dict((u['phid'], u) for u in users)
    except ConduitClientError as ex:
        pass

    commit_msg = _get_commit_msg(rev, user_map)

    prev_commit = None
    for diff in rev.diffs:
        info = CommitInfo(author_name=diff.all_params['authorName'],
                          author_email=diff.all_params['authorEmail'],
                          timestamp=diff.all_params['dateCreated'],
                          message=commit_msg,
                          prev=prev_commit)
        commit = arc_scm.apply_diff(diff, rev, info)
        prev_commit = commit


def _get_commit_msg(rev, user_map):
    reviewer_names = ', '.join(user_map[phid]['userName']
                               for phid in rev.reviewer_phids)

    template = '''\
{title}

Summary:
{summary}

Test Plan:
{test_plan}

Reviewers: {reviewers}

Differential Revision: {uri}
'''
    return template.format(title=rev.title,
                           summary=rev.summary,
                           test_plan=rev.test_plan,
                           reviewers=reviewer_names,
                           uri=rev.uri)


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
