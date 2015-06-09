#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
import logging

from gitreview.git.exceptions import NoSuchCommitError
from gitreview.hgapi import FakeCommit

from mercurial.context import memctx, memfilectx
from mercurial.scmutil import revrange


class BadPatchError(Exception):
    def __init__(self, node, paths):
        msg = ('cannot apply patch to %s: %s' % (node.hex(), paths))
        super(BadPatchError, self).__init__(msg)
        self.node = node
        self.paths = paths


class PathPatchError(Exception):
    pass


class ArcanistHg(object):
    def __init__(self, repo):
        self.repo = repo

    def apply_diff(self, diff):
        logging.debug('Applying diff %s', diff.id)

        # Phabricator lists the base revision that this diff applied to.
        # Check to see if this is a known revision in our repository.
        parent = self.find_base_commit(diff)
        if parent is not None:
            # Excellent, the base commit exists in our repository.
            # The diff should apply cleanly to it.
            logging.debug('found base revision %s for diff %s',
                          parent.node.hex(), diff.id)
            return self._apply_diff(parent.node, diff)

        # We didn't find the base commit specified by phabricator.
        # Try to find another commit that works instead.
        #
        # Find all commits that modified the files in question.
        commit_nums = set()
        for change in diff.changes:
            old_path = change.old_path.encode('utf-8')
            flog = self.repo.repo.file(old_path)
            for idx in flog:
                commit_num = flog.linkrev(idx)
                commit_nums.add(commit_num)

        # Sort the commit numbers, from highest (most recent) to lowest
        commit_nums = sorted(commit_nums, reverse=True)

        # Try to apply the patch to each of these diffs.
        #
        # TODO: We could be smarter here by keeping track of how many files the
        # diff doesn't apply to, and how many hunks/lines fail for each file.
        # We could then target only changes that affect the files that still
        # have failures.
        #
        # This would also let us abort if the patch attempts start getting
        # worse rather than better.
        for num in commit_nums:
            node = self.repo.repo[num]
            logging.debug('trying to apply diff %s to %s', diff.id, node.hex())
            try:
                return self._apply_diff(node, diff)
            except BadPatchError as ex:
                cur_bad_paths = ex.paths

        raise Exception('unable to find a commit where diff %s applies' %
                        (diff.id,))

    def _apply_diff(self, node, diff):
        # Compute the new file contents for each path.
        # Throw an error if some of them don't apply cleanly.
        new_data = {}
        bad_paths = {}
        for change in diff.changes:
            old_path = change.old_path.encode('utf-8')
            new_path = change.current_path.encode('utf-8')
            try:
                path_data = self._apply_diff_path(node, diff, change, old_path)
                new_data[new_path] = path_data
                if old_path != new_path:
                    new_data[old_path] = None
            except PathPatchError as ex:
                bad_paths[old_path] = ex
        if bad_paths:
            raise BadPatchError(node, bad_paths)

        parent_ctx = self.repo.repo[node]
        def getfilectx(repo, memctx, path):
            data = new_data[path]
            if data is None:
                raise IOError('file was deleted')
            return memfilectx(repo, path, data)

        fileset = set(new_data)

        # TODO: Also add the previous rev from the diff as a parent.
        parents = (node, None)
        # TODO: Put a useful message here
        msg = 'test commit'
        ctx = memctx(self.repo.repo, parents, msg, fileset, getfilectx)
        node_id = self.repo.repo.commitctx(ctx)
        node = self.repo.repo[node_id]
        logging.debug('committed new node: %r' % (node.hex(),))

    def _apply_diff_path(self, node, diff, change, path):
        if change is None:
            return None

        old_data = self.repo.getBlobContents(node, path)
        return self._patch_data(old_data, change)

    def _patch_data(self, old, change):
        old_lines = old.split('\n')
        new_lines = []
        for hunk in change.hunks:
            # Subtract 1 since the hunk offsets are 1-indexed instead of
            # 0-indexed.  (Line 1 is at old_lines[0])
            old_idx = hunk['oldOffset'] - 1
            for line in hunk['corpus'].splitlines():
                if line.startswith(' '):
                    old_line = old_lines[old_idx]
                    if old_line != line[1:]:
                        raise PathPatchError('mismatch at line %d: %r != %r' %
                                             (old_idx, old_line, line))
                    new_lines.append(old_line)
                    old_idx += 1
                elif line.startswith('-'):
                    old_line = old_lines[old_idx]
                    if old_line != line[1:]:
                        raise PathPatchError('mismatch at line %d: %r != %r' %
                                             (old_idx, old_line, line))
                    old_idx += 1
                elif line.startswith('+'):
                    new_lines.append(line[1:])
                else:
                    raise Exception('unexpected line in diff hunk: %r' %
                                    (line,))

        return '\n'.join(new_lines) + '\n'

    def find_base_commit(self, diff):
        arc_base_rev = diff.all_params['sourceControlBaseRevision']
        # The mercurial library code complains about unicode strings,
        # so encode this to a byte string.
        arc_base_rev = arc_base_rev.encode('utf-8')

        # First check to see if we can find the parent commit
        if diff.all_params['sourceControlSystem'] == 'git':
            parent_rev = 'g' + arc_base_rev
        elif diff.all_params['sourceControlSystem'] == 'hg':
            parent_rev = arc_base_rev
        else:
            # Unknown source repo type
            return None

        try:
            commit = self.repo.getCommit(parent_rev)
        except NoSuchCommitError:
            return None
            print(commit)

        return commit
