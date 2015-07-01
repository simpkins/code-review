#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
import errno
import heapq
import logging
import os
import re

from gitreview.git.exceptions import NoSuchCommitError
from gitreview.hgapi import FakeCommit

from mercurial.context import memctx, memfilectx
from mercurial.scmutil import revrange
import mercurial.error
import mercurial.util


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

        # We didn't find the base commit specified by phabricator.
        # Try to find another commit that works instead.
        #
        # Try each commit that modified any of the files in question.
        #
        # TODO: We could be smarter here by keeping track of how many files the
        # diff doesn't apply to, and how many hunks/lines fail for each file.
        # We could then target only changes that affect the files that still
        # have failures.
        #
        # This would also let us abort if the patch attempts start getting
        # worse rather than better.
        for node in self._candidate_commits(diff, metadata):
            logging.debug('trying to apply diff %s to %s', diff.id, node.hex())
            try:
                return self._apply_diff(node, diff, rev, metadata)
            except BadPatchError as ex:
                cur_bad_paths = ex.paths

        raise Exception('unable to find a commit where diff %s applies' %
                        (diff.id,))

    def _candidate_commits(self, diff, metadata):
        # If we have a previously applied diff, try it's parent.
        # This is likely to be a good guess for where to apply the diff.
        if metadata.prev_commit is not None:
            yield metadata.prev_commit.node.p1()

        # If we aren't using remotefilelog, then we can do a fast walk
        # of the filelogs.  If the remotefilelog extension is being used,
        # we have to walk backwards through ancestor commits of the relevant
        # local heads.
        flog = self.repo.repo.file('.')
        if hasattr(flog, '__iter__'):
            # We can use the faster filelog method
            candidates_fn = self._normal_candidate_commits
        else:
            # We have to use the remotefilelog-compatible version
            candidates_fn = self._remotefilelog_candidate_commits

        for node in candidates_fn(diff):
            yield node

    def _remotefilelog_candidate_commits(self, diff):
        '''
        Walk all ancestors of remote/master which touched any of the modified
        files.
        '''
        # We'll walk through all commits that changed any of the modified
        # files.  First get ancestor generators for each file  First get
        # ancestor generators for each file.

        seen = set()
        rev_heap = []
        cidx = 0
        relevant_heads = 'bookmark() + (head() - hidden() - public())'
        for commit in self.repo.repo.set(relevant_heads):
            cidx += 1

            for path in self._old_paths(diff):
                try:
                    anc = commit.filectx(path).ancestors()
                except mercurial.error.ManifestLookupError:
                    continue
                try:
                    rev = next(anc).linkrev()
                    if rev not in seen:
                        rev_heap.append((-rev, anc))
                        seen.add(rev)
                except StopIteration:
                    pass

        # Now walk backwards through the ancestors, from oldest to newest
        heapq.heapify(rev_heap)
        while rev_heap:
            rev = -rev_heap[0][0]
            gen = rev_heap[0][1]
            yield self.repo.repo[rev]

            try:
                next_rev = next(gen).linkrev()
                if next_rev in seen:
                    next_rev = None
            except StopIteration:
                next_rev = None

            if next_rev is None:
                heapq.heappop(rev_heap)
            else:
                new_item = (-next_rev, gen)
                heapq.heappushpop(rev_heap, new_item)
                seen.add(next_rev)

    def _normal_candidate_commits(self, diff):
        '''
        Walk all commits which touched any of the files modified by this diff.

        This method is fast, but doesn't work with the remotefilelog extension.
        '''
        commit_nums = set()
        for path in self._old_paths(diff):
            flog = self.repo.repo.file(path)
            for idx in flog:
                commit_num = flog.linkrev(idx)
                commit_nums.add(commit_num)

        # If this commit only added new files, we should be able to apply it
        # any where.
        if not commit_nums:
            raise Exception('TODO: apply onto remote/master')

        # Sort the commit numbers, from highest (most recent) to lowest
        commit_nums.sort(reverse=True)
        return [self.repo.repo[num] for num in commit_nums]

    def _old_paths(self, diff):
        for change in diff.changes:
            if change.old_path is None:
                continue
            yield change.old_path.encode('utf-8')

    def _apply_diff(self, node, diff, rev, metadata):
        # Compute the new file contents for each path.
        # Throw an error if some of them don't apply cleanly.
        new_data = {}
        bad_paths = {}
        for change in diff.changes:
            if change.old_path is None:
                old_path = None
            else:
                old_path = change.old_path.encode('utf-8')
            new_path = change.current_path.encode('utf-8')
            try:
                path_data = self._apply_diff_path(node, diff, change, old_path)

                # mercurial will choke with a pretty unhelpful exception
                # backtrace if we give it unicode data.
                assert not isinstance(path_data, unicode)

                new_data[new_path] = path_data
                if old_path is not None and old_path != new_path:
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

        if metadata.prev_commit is None:
            parents = (node, None)
        else:
            parents = (node, metadata.prev_commit.node)

        msg = metadata.message
        user = '%s <%s>' % (metadata.author_name, metadata.author_email)
        date = mercurial.util.makedate(metadata.timestamp)

        ctx = memctx(self.repo.repo, parents, msg, fileset, getfilectx,
                     user=user, date=date)
        node_id = self.repo.repo.commitctx(ctx)
        node = self.repo.repo[node_id]
        logging.debug('committed new node: %r' % (node.hex(),))

        self._save_diff_mapping(diff, node)
        return FakeCommit(node)

    def _apply_diff_path(self, node, diff, change, path):
        if change is None:
            return None

        if path is None:
            old_data = b''
        else:
            try:
                old_data = self.repo.getBlobContents(node, path)
            except mercurial.error.ManifestLookupError:
                raise BadPatchError(node, [path])
        return self._patch_data(old_data, change)

    def _patch_data(self, old, change):
        old_lines = old.split('\n')
        new_lines = []
        for hunk in change.hunks:
            # Subtract 1 since the hunk offsets are 1-indexed instead of
            # 0-indexed.  (Line 1 is at old_lines[0])
            old_idx = hunk['oldOffset'] - 1
            for line in hunk['corpus'].splitlines():
                line = line.encode('utf-8')

                if old_idx >= len(old_lines):
                    raise PathPatchError('mismatch at line %d: old file '
                                         'ends at line %d' %
                                         (old_idx + 1, len(old_lines)))

                if line.startswith(' '):
                    old_line = old_lines[old_idx]
                    if old_line != line[1:]:
                        raise PathPatchError('mismatch at line %d: %r != %r' %
                                             (old_idx + 1, old_line, line))
                    new_lines.append(old_line)
                    old_idx += 1
                elif line.startswith('-'):
                    old_line = old_lines[old_idx]
                    if old_line != line[1:]:
                        raise PathPatchError('mismatch at line %d: %r != %r' %
                                             (old_idx + 1, old_line, line))
                    old_idx += 1
                elif line.startswith('+'):
                    new_lines.append(line[1:])
                else:
                    raise Exception('unexpected line in diff hunk: %r' %
                                    (line,))

        return b'\n'.join(new_lines) + b'\n'

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

    def _get_diff_mapping_path(self):
        return os.path.join(self.repo.workingDir, '.hg', 'phabricator_diffs')

    def _load_diff_mappings(self):
        results = {}
        regex = re.compile(r'^([0-9]+): ([0-9a-fA-F]+)$')
        try:
            with open(self._get_diff_mapping_path(), 'r') as f:
                for line in f:
                    m = regex.match(line)
                    diff_id = int(m.group(1))
                    node_id = m.group(2)
                    results[diff_id] = node_id
        except IOError as ex:
            if ex.errno != errno.ENOENT:
                raise
            return {}

        return results

    def _save_diff_mapping(self, diff, node):
        # We use a custom format here instead of treating the entire file as a
        # single json chunk.  This way we can just append one line at a time,
        # instead of having to re-write the entire file each time.

        line = '%d: %s\n' % (diff.id, node.hex())
        # TODO: We should really add some locking around this update.
        with open(self._get_diff_mapping_path(), 'a') as f:
            f.write(line)

    def find_diff_commits(self, rev):
        mappings = self._load_diff_mappings()

        results = {}
        for diff in rev.diffs:
            node_id = mappings.get(diff.id)
            if node_id is not None:
                node = self.repo.repo[node_id]
                results[diff.id] = FakeCommit(node)

        return results
