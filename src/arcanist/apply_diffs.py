#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
from .conduit import ArcanistConduitClient
from .err import ConduitClientError, PatchFailedError
from .working_copy import WorkingCopy, NoArcConfigError
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
            self.arc_scm = arc_hg.ArcanistHg(repo)
        else:
            self.arc_scm = arc_git.ArcanistGit(repo)

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

            # Figure out what directory these diff changes apply to.
            # Store that as a property of the diff object.
            diff.repo_path_prefix = self._get_path_prefix(diff)

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
        template = u'''\
{title}

Summary:
{summary}

Test Plan:
{test_plan}

Reviewers: {reviewers}

Differential Revision: {uri}
'''
        unicode_msg = template.format(title=self.rev.title,
                                      summary=self.rev.summary,
                                      test_plan=self.rev.test_plan,
                                      reviewers=reviewer_names,
                                      uri=self.rev.uri)
        return unicode_msg.encode('utf-8')

    def _get_path_prefix(self, diff):
        # Figure out if the diff paths are relative to a particular directory
        # in the repository.  Stash that as a property of the diff object
        # so we can find it later.
        #
        # By default, assume the diff applies to the directory where we found
        # the .arcconfig file.
        default_prefix = os.path.relpath(self.arc_dir.root,
                                         self.repo.workingDir)
        diff_project = diff.all_params.get('projectName')
        if not diff_project:
            return default_prefix

        if diff_project == self.arc_dir.config.project_id:
            return default_prefix

        # Check to see if there is an arcconfig file at the root of the
        # repository.
        try:
            root_arc = WorkingCopy(self.repo.workingDir)
            if diff_project == root_arc.config.project_id:
                return os.path.relpath(root_arc.root, self.repo.workingDir)
        except NoArcConfigError:
            pass

        raise Exception('cannot apply diff for unknown arcanist project %s' %
                        diff_project)
