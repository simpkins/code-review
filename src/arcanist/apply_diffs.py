#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from .conduit import ArcanistConduitClient
from .err import ConduitClientError, PatchFailedError
from .working_copy import WorkingCopy, NoArcConfigError
from . import revision
from . import git as arc_git

try:
    from . import hg as arc_hg
    from scmreview import hgapi
    have_hg_support = True
except ImportError:
    have_hg_support = False

import os
import logging
import pprint
import time


def apply_diffs(repo, rev_id):
    return _Applier(repo).run(rev_id)


class CommitInfo(object):
    def __init__(self, author_name, author_email, timestamp, message, prev):
        self.author_name = author_name
        self.author_email = author_email
        self.timestamp = timestamp
        self.message = message
        self.prev_commit = prev


class _Applier(object):
    def __init__(self, repo):
        self.conduit = None
        self._commit_msg_cache = {}
        self._user_cache = {}

        self.repo = repo
        self.arc_dir = WorkingCopy(os.getcwd())
        if have_hg_support and isinstance(repo, hgapi.Repository):
            self.arc_scm = arc_hg.ArcanistHg(repo)
        else:
            self.arc_scm = arc_git.ArcanistGit(repo)

        self._rev_results = {}

    def run(self, rev_id):
        # The same _Applier object may be asked to apply multiple revisions
        # when processing dependencies.  Keep track of which revisions we have
        # already processed or started processing.
        #
        # This avoids repeating work and also helps us avoid looping forever if
        # there is a cycle in the dependency list.
        if rev_id in self._rev_results:
            results = self._rev_results[rev_id]
            if results is None:
                # We were invoked recursively and are still in the process
                # of applying diffs for this revision.  Just return the empty
                # list so our caller can continue.  Our original invocation
                # will complete later to try and finish applying diffs for this
                # revision.
                return []
            return results[:]
        self._rev_results[rev_id] = None

        self.conduit = ArcanistConduitClient(self.arc_dir)
        self.conduit.connect()
        rev = revision.get_revision(self.conduit, rev_id)

        existing = self.arc_scm.find_diff_commits(rev)

        # If a previous run skipped some early diffs, and applied later ones,
        # only start processing after the diffs that were already applied.
        # Don't bother trying to apply earlier diffs that we already
        # tried and failed to apply before.
        # If we have already app
        results = []
        to_apply = []
        for diff_idx, diff in enumerate(rev.diffs):
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
            info = self._get_commit_info(rev, diff, prev_commit)

            # Figure out what directory these diff changes apply to.
            # Store that as a property of the diff object.
            diff.repo_path_prefix = self._get_path_prefix(diff)

            try:
                commit = self.arc_scm.apply_diff(self, rev, diff, info)
                results.append(commit)
            except PatchFailedError as ex:
                # We always need to apply the current diff (the last one in the
                # list) in order for review.
                if diff_idx + 1 == len(rev.diffs):
                    raise

                # However, for previous diffs that aren't the current one, just
                # continue trying to apply later diffs, rather than completely
                # failing here.
                logging.error('Failed to find a changeset where diff %s (%s) '
                              'applies. Ignoring it, and continuing anyway',
                              diff_idx + 1, diff.id)
                continue

        self._rev_results[rev_id] = results[:]
        return results

    def _get_commit_info(self, rev, diff, parent_commit):
        commit_msg = self._get_commit_msg(rev)

        # Ugh.  Diffs created by jellyfish are missing many parameters.
        # Pull data from the revision if it isn't present on the diff.
        author_name = diff.all_params.get('authorName')
        if not author_name:
            author_phid = rev.author_phid
            author_name, author_email = self._get_user_info(author_phid)
        else:
            author_email=diff.all_params['authorEmail']

        timestamp = diff.all_params.get('dateCreated')
        if timestamp is None:
            # Just default to the current time.
            timestamp = time.time()

        return CommitInfo(author_name=author_name,
                          author_email=author_email,
                          timestamp=diff.all_params['dateCreated'],
                          message=commit_msg,
                          prev=parent_commit)

    def _get_user_info(self, phid):
        if phid in self._user_cache:
            return self._user_cache[phid]

        info = self.conduit.call_method('user.query', phids=[phid])[0]
        name = info['realName']
        email = '%s@fb.com' % info['userName']

        self._user_cache[phid] = name, email
        return name, email

    def _get_commit_msg(self, rev):
        commit_msg = self._commit_msg_cache.get(rev.id, None)
        if commit_msg is None:
            commit_msg = self._compute_commit_msg(rev)
            self._commit_msg_cache[rev.id] = commit_msg
        return commit_msg

    def _compute_commit_msg(self, rev):
        relevant_phids = [rev.author_phid] + rev.reviewer_phids
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
                                   for phid in rev.reviewer_phids)
        template = u'''\
{title}

Summary:
{summary}

Test Plan:
{test_plan}

Reviewers: {reviewers}

Differential Revision: {uri}
'''
        unicode_msg = template.format(title=rev.title,
                                      summary=rev.summary,
                                      test_plan=rev.test_plan,
                                      reviewers=reviewer_names,
                                      uri=rev.uri)
        return unicode_msg.encode('utf-8')

    def _get_path_prefix(self, diff):
        # Figure out if the diff paths are relative to a particular directory
        # in the repository.  Stash that as a property of the diff object
        # so we can find it later.
        #
        # By default, assume the diff applies to the directory where we found
        # the .arcconfig file.
        working_dir = self.repo.get_working_dir()
        assert working_dir is not None
        default_prefix = os.path.relpath(self.arc_dir.root, working_dir)
        diff_project = diff.all_params.get('projectName')
        if not diff_project:
            return default_prefix

        if diff_project == self.arc_dir.config.project_id:
            return default_prefix

        # Check to see if there is an arcconfig file at the root of the
        # repository.
        try:
            root_arc = WorkingCopy(working_dir)
            if diff_project == root_arc.config.project_id:
                return os.path.relpath(root_arc.root, working_dir)
        except NoArcConfigError:
            pass

        # Just return the default prefix.
        # We used to fail here if the project ID in phabricator did not match
        # the local project ID in .arcconfig; This matched the original
        # behavior of "arc patch".
        #
        # However, some Facebook repositories now use "subproject" IDs in
        # phabricator.  The project ID listed in phabricator is usually a
        # subproject ID, and does not match the top-level project ID in
        # .arcconfig any more.
        return default_prefix
