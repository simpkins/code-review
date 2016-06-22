#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
import arcanist.gitapply
from gitreview.diffcamp.dcgit import get_dc_commit_chain
from gitreview.git.exceptions import NoSuchCommitError
from gitreview.git.commit import log_commit_paths

import logging


class ArcanistGit(object):
    def __init__(self, repo):
        self.repo = repo

        # If the arcanist project root is a subdirectory of the repository
        # root, we need to modify the paths in the phabricator diff data
        # to include the prefix to the arcanist project.
        #
        # TODO: Actually implement this correctly.  At the moment I don't
        # have any git repositories affected by this.

    def find_diff_commits(self, rev):
        chain = get_dc_commit_chain(self.repo, rev.id)

        results = {}
        for dc_commit in chain:
            results[dc_commit.diffId] = dc_commit.commit

        return results

    def apply_diff(self, diff, rev, metadata):
        logging.debug('Applying diff %s', diff.id)

        # Phabricator lists the base revision that this diff applied to.
        # Check to see if this is a known revision in our repository.
        parent = self.find_base_commit(diff)
        if parent is not None:
            # Excellent, the base commit exists in our repository.
            # The diff should apply cleanly to it.
            logging.debug('found base revision %s for diff %s',
                          parent.node.hex(), diff.id)
            return self._apply_diff(parent.node, diff, rev, metadata)

        # TODO: Walk over all recent commits that touched the affected files,
        # and see if the diff applies to any of them.

        changed_paths = []
        for change in diff.changes:
            if change.old_path is None:
                # Ignore files added by this diff.  There shouldn't be any
                # conflicts applying them to any commit.
                continue
            changed_paths.append(change.old_path)

        if not changed_paths:
            # This diff may have only added new files.
            # In this case it should apply cleanly pretty much anywhere.
            parent = self.repo.getCommit('origin/master')
            return self._apply_diff(parent, diff, rev, metadata)

        origin = 'remotes/origin/master'
        for commit in log_commit_paths(self.repo, [origin], changed_paths):
            try:
                return self._apply_diff(commit, diff, rev, metadata)
            #except BadPatchError as ex:
            except Exception as ex:
                raise
                raise Exception('TODO: got %r error: %s' % (type(ex), ex))
                cur_bad_paths = ex.paths

        raise Exception('TODO')

    def _apply_diff(self, commit, diff, rev, metadata):
        if metadata.prev_commit is None:
            parents = (commit.sha1,)
        else:
            parents = (commit.sha1, metadata.prev_commit.sha1)
        new_commit_sha1 = arcanist.gitapply.apply_diff(self.repo, diff,
                                                       commit.sha1, parents)
        return self.repo.getCommit(new_commit_sha1)

    def find_base_commit(self, diff):
        arc_base_rev = diff.all_params['sourceControlBaseRevision']
        # The mercurial library code complains about unicode strings,
        # so encode this to a byte string.
        arc_base_rev = arc_base_rev.encode('utf-8')

        # First check to see if we can find the parent commit
        if diff.all_params['sourceControlSystem'] == 'git':
            parent_rev = 'g' + arc_base_rev
        elif diff.all_params['sourceControlSystem'] == 'hg':
            # TODO: Do we have a mapping from hg revision IDs to git?
            return None
        else:
            # Unknown source repo type
            return None

        try:
            commit = self.repo.getCommit(parent_rev)
        except NoSuchCommitError:
            return None
            print(commit)

        return commit
