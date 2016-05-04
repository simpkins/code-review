#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
import errno
import heapq
import json
import logging
import os
import re

from .err import PatchFailedError
from .revision import ChangeSet

from gitreview.git.exceptions import NoSuchCommitError
from gitreview.hgapi import FakeCommit

from mercurial.context import memctx, memfilectx
from mercurial.scmutil import revrange
import mercurial.error
import mercurial.util


SVN_REV_REGEX = re.compile(r'^svn\+ssh://.*@(?P<svn_rev>[0-9]+)$')


class BadPatchError(PatchFailedError):
    def __init__(self, node, paths):
        msg = ('cannot apply patch to %s: %s' % (node.hex(), paths))
        super(BadPatchError, self).__init__(msg)
        self.node = node
        self.paths = paths


class PathPatchError(Exception):
    pass


class ArcanistHg(object):
    def __init__(self, repo, arc_dir):
        self.repo = repo
        self.arc_dir = arc_dir
        self.debug_patches = False

        # If the arcanist project root is a subdirectory of the repository
        # root, we need to modify the paths in the phabricator diff data
        # to include the prefix to the arcanist project.
        self.path_prefix = os.path.relpath(self.arc_dir.root,
                                           self.repo.workingDir)

    def apply_diff(self, diff, rev, metadata):
        logging.debug('Applying diff %s', diff.id)

        # TODO: Handle fbcode<-->fbsource path name translations.
        # The diff's project name can be found in
        # diff.all_params['projectName'].

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
        # The phabricator revision does have a 'local:commits' field, but it is
        # unfortunately useless.  Rather than listing all local commits since
        # the last public commit, it just lists the one single commit since ".^"
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
        for node in self._candidate_commits(rev, diff, metadata):
            node_info = self._fmt_commit_info(node)
            logging.debug('trying to apply diff %s to %s', diff.id, node_info)
            try:
                return self._apply_diff(node, diff, rev, metadata)
            except BadPatchError as ex:
                logging.debug('  Patch failed:')
                for path, reason in ex.paths.items():
                    logging.debug('    %s: %s', path, reason)

        raise PatchFailedError('unable to find a commit where diff %s '
                               'applies' % (diff.id,))

    def _fmt_commit_info(self, node):
        short_hex = node.hex()[:7]
        summary = node.description().split('\n', 1)[0][:30]
        return '%s %s: %s' % (short_hex, node.user(), summary)

    def _candidate_commits(self, rev, diff, metadata):
        # If we have a previously applied diff, try it's parent.
        # This is likely to be a good guess for where to apply the diff.
        if metadata.prev_commit is not None:
            yield metadata.prev_commit.node.p1()

        # If you want to explicitly try specific commits,
        # you can list them here.
        explicit_results = []
        if explicit_results:
            for node in self.repo.repo.set(explicit_results):
                yield node
            return

        if self.debug_patches:
            print('---- Rev ----')
            print(json.dumps(rev.all_params, indent=2))
            print('---- Diff ----')
            print(json.dumps(diff.all_params, indent=2))

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

        # If all else fails, try master, @, and .
        for rev in ('master', '@', '.'):
            try:
                node = self.repo.repo[rev]
            except mercurial.error.RepoLookupError:
                continue
            yield node

    def _remotefilelog_candidate_commits(self, diff):
        '''
        Walk all ancestors of remote/master which touched any of the modified
        files.
        '''
        # With remotefilelog, we have to walk backwards down the commit DAG
        # to find commits that modified the files we are interested in.
        #
        # This is the list of heads we start from.  We include remote/master,
        # plus any other local heads which are not public.
        #
        # We exclude other public heads, since the repos I work on generally
        # have many other public tags and heads that I don't care about, and
        # are expensive to search through.
        relevant_heads = (
            'remote/master '
            '+ ((head() + parents(hidden())) - hidden()) '
            '- public()'
        )

        commits_to_check = set(self.repo.repo.set('remote/master'))

        # The following operations are unfortunately quite slow with a
        # lot of heads.  To speed things up, only look at heads that
        # were created by the same author as the diff we are applying.
        heads = self.repo.repo.set(relevant_heads)
        for c in heads:
            if diff.author_email in c.user():
                commits_to_check.add(c)

        # For each head
        seen = set()
        rev_heap = []
        for commit in commits_to_check:
            # For each file changed by this diff, get the filectx() in
            # this commit.
            for path in self._old_paths(diff):
                try:
                    fctx = commit.filectx(path)
                except mercurial.error.ManifestLookupError:
                    continue

                # Get the most recent commit that touched this file.
                # If we haven't already found it via another head,
                # also get an ancestor generator to let us walk backwards
                # from this commit, and add it to rev_heap.
                rev = fctx.linkrev()
                if rev not in seen:
                    anc = fctx.ancestors()
                    rev_heap.append((-rev, anc))
                    seen.add(rev)

        # Now walk backwards through the ancestors, from oldest to newest.
        #
        # At each step, we find the most recent commit, yield it to our caller,
        # and advance it's ancestor generator back one more step.
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

    def _munge_change_path(self, change_path):
        if change_path is None:
            return None
        path = change_path.encode('utf-8')
        path = os.path.normpath(os.path.join(self.path_prefix, path))
        return path

    def _old_path(self, change):
        return self._munge_change_path(change.old_path)

    def _current_path(self, change):
        return self._munge_change_path(change.current_path)

    def _old_paths(self, diff):
        for change in diff.changes:
            if change.old_path is None:
                continue
            yield self._old_path(change)

    def _apply_diff(self, node, diff, rev, metadata):
        # Compute the new file contents for each path.
        # Throw an error if some of them don't apply cleanly.
        new_data = {}
        bad_paths = {}
        for change in diff.changes:
            try:
                self._apply_diff_path(node, change, new_data)
            except PathPatchError as ex:
                bad_path = change.current_path or change.old_path
                bad_paths[self._munge_change_path(bad_path)] = ex
        if bad_paths:
            raise BadPatchError(node, bad_paths)

        parent_ctx = self.repo.repo[node]
        def getfilectx(repo, memctx, path):
            (data, old_path) = new_data[path]
            if data is None:
                return None
            else:
                # mercurial will choke with a pretty unhelpful exception
                # backtrace if we give it unicode data.
                assert not isinstance(data, unicode), \
                        'BUG: generated unicode data for path %r' % path
            return memfilectx(repo, path, data, copied=old_path)

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

    def _apply_diff_path(self, node, change, new_data):
        if change.type == ChangeSet.TYPE_ADD:
            new_path = self._current_path(change)
            # Check that the file doesn't exist
            self._check_file_not_present(node, new_path)
            new_data[new_path] = (self._patch_data(None, change), None)
        elif change.type == ChangeSet.TYPE_CHANGE:
            new_path = self._current_path(change)
            old_path = self._old_path(change)
            assert new_path == old_path, '%r != %r' % (new_path, old_path)
            old_data = self._get_path_data(node, old_path)
            new_data[new_path] = (self._patch_data(old_data, change), None)
        elif change.type == ChangeSet.TYPE_DELETE:
            new_path = self._current_path(change)
            self._check_file_present(node, new_path)
            new_data[new_path] = (None, None)
        elif change.type == ChangeSet.TYPE_MOVE_AWAY:
            new_path = self._current_path(change)
            assert change.old_path is None, \
                    'non-empty old path %r' % (change.old_path,)
            new_data[new_path] = (None, None)
        elif change.type == ChangeSet.TYPE_COPY_AWAY:
            # Nothing to do for this case
            pass
        elif change.type in (ChangeSet.TYPE_MOVE_HERE,
                             ChangeSet.TYPE_COPY_HERE):
            new_path = self._current_path(change)
            old_path = self._old_path(change)
            assert new_path != old_path, '%r != %r' % (new_path, old_path)
            # Check that the destination doesn't exist
            self._check_file_not_present(node, new_path)
            old_data = self._get_path_data(node, old_path)
            # Set the contents for the new file
            new_data[new_path] = (self._patch_data(old_data, change), old_path)
            # Note: we don't delete the old file when processing this
            # ChangeSet.  For moves, there will be a corresponding
            # TYPE_MOVE_AWAY change, and we will delete the old path there.
        elif change.type == ChangeSet.TYPE_MULTICOPY:
            raise Exception('unhandled TYPE_MULTICOPY change for path %r' %
                            self._current_path(change))
        elif change.type == ChangeSet.TYPE_MESSAGE:
            raise Exception('unhandled TYPE_MESSAGE change for path %r' %
                            self._current_path(change))
        elif change.type == ChangeSet.TYPE_CHILD:
            raise Exception('unhandled TYPE_CHILD change for path %r' %
                            self._current_path(change))
        else:
            raise Exception('unhandled %r change for path %r' %
                            (change.type, self._current_path(change)))

    def _get_path_data(self, node, path):
        try:
            return self.repo.getBlobContents(node, path)
        except mercurial.error.ManifestLookupError:
            raise PathPatchError('file %r does not exist in commit %s' %
                                 (path, node.hex()))

    def _check_file_present(self, node, path):
        try:
            node[path]
        except mercurial.error.ManifestLookupError:
            raise PathPatchError('file %r does not exist in commit %s' %
                                 (path, node.hex()))

    def _check_file_not_present(self, node, path):
        try:
            node[path]
            raise PathPatchError('file %r already exists in commit %s' %
                                 (path, node.hex()))
        except mercurial.error.ManifestLookupError:
            pass

    def _patch_data(self, old, change):
        # Phabricator will include this string at the end of the diff
        # if the file was missing a terminating newline.
        PHABRICATOR_NO_END_NEWLINE = r'\ No newline at end of file'

        if not change.hunks:
            # This can happen in cases of files that were moved
            # or copied but had no changes to the file contents.
            return old

        if old is not None:
            old_lines = old.split('\n')
        else:
            old_lines = None
        new_lines = []
        terminating_newline = True
        old_idx = -1
        for hunk in change.hunks:
            # Subtract 1 since the hunk offsets are 1-indexed instead of
            # 0-indexed.  (Line 1 is at old_lines[0])
            old_idx = hunk['oldOffset'] - 1
            corpus_lines = hunk['corpus'].splitlines()
            for line_idx, line in enumerate(corpus_lines):
                line = line.encode('utf-8')

                # Even though phabricator does include
                # hunk['isMissingOldNewline'] and
                # hunk['isMissingNewNewline'] properties, these doesn't
                # seem to be set properly.  Instead it puts a bogus line
                # at the end of the diff output.
                if (line_idx + 1 == len(corpus_lines) and
                        line == PHABRICATOR_NO_END_NEWLINE):
                    terminating_newline = False
                    break

                if line.startswith('+'):
                    new_lines.append(line[1:])
                    continue

                if old is None:
                    raise PathPatchError('bad patch data: specified '
                                         'old file data for newly created '
                                         'file')

                if old_idx >= len(old_lines):
                    raise PathPatchError('mismatch at line %d: old file '
                                         'ends at line %d' %
                                         (old_idx + 1, len(old_lines)))
                if old_idx < 0:
                    # Phabricator will specify oldOffset as 0 when
                    # the old file was empty.  It shoudnl't emit any lines
                    # starting with ' ' or '-' in this case.
                    raise PathPatchError('bad patch data: specified '
                                         'contents at invalid line number '
                                         '%d in old file' % (old_idx + 1))

                if line.startswith(' '):
                    keep_line = True
                elif line.startswith('-'):
                    keep_line = False
                else:
                    raise Exception('unexpected line in diff hunk: %r' %
                                    (line,))

                old_line = old_lines[old_idx]
                if old_line != line[1:]:
                    # TODO: Support some patch fuzzing here, if there is a
                    # slight mismatch in parts of the file that weren't
                    # affected by the diff.
                    raise PathPatchError('mismatch at line %d:\n'
                                         '  expected: %r\n'
                                         '  found:    %r' %
                                         (old_idx + 1, old_line, line[1:]))
                old_idx += 1
                if keep_line:
                    new_lines.append(old_line)

        # We should have used all of the old data when we are done.
        if old is None:
            # old_idx should be -1 here.  (Since oldOffset will be specified as
            # 0 in the diff hunk, and we shouldn't have ever incremented
            # old_idx.)
            if old_idx != -1:
                raise PathPatchError('mismatch: old file was empty')
        else:
            # Make sure we used up all of the old file contents
            if old_idx + 1 == len(old_lines):
                # We used all but the last entry in old_lines.
                # If the old file had a terminating newline, then
                # old_lines[idx] will be empty, and this is fine.
                # Otherwise there is still some unused data.
                if old_lines[old_idx]:
                    raise PathPatchError('patch stopped prior to the last '
                                         'line of the old file (which was '
                                         'missing a terminating newline)')
            elif old_idx != len(old_lines):
                # The patch did not use up all of the old data.
                raise PathPatchError('patch ended at line %d of old file, '
                                     'while file had %d lines' %
                                     (old_idx + 1, len(old_lines)))

        result = b'\n'.join(new_lines)
        if terminating_newline:
            result += b'\n'
        return result

    def find_base_commit(self, diff):
        arc_base_rev = diff.all_params['sourceControlBaseRevision']
        # The mercurial library code complains about unicode strings,
        # so encode this to a byte string.
        arc_base_rev = arc_base_rev.encode('utf-8')

        # First check to see if we can find the parent commit
        #
        # Look for a subversion style revision name first.  In git-svn and
        # hg-svn repos, arc will set the sourceControlSystem to git/hg,
        # but will still use a subversion-style revision name.
        m = SVN_REV_REGEX.match(arc_base_rev)
        if m:
            parent_rev = 'r' + m.group('svn_rev')
        elif diff.all_params['sourceControlSystem'] == 'git':
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
