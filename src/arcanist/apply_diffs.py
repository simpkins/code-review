#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from . import revision
from . import hg as arc_hg
from . import git as arc_git

from gitreview import hgapi

import pprint


def apply_diffs(repo, rev_id):
    rev = revision.get_revision(repo.workingDir, rev_id)
    if isinstance(repo, hgapi.Repository):
        arc_scm = arc_hg.ArcanistHg(repo)
    else:
        arc_scm = arc_hg.ArcanistGit(repo)

    for diff in rev.diffs:
        arc_scm.apply_diff(diff)


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
