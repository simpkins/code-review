#!/usr/bin/python -tt
#
# Copyright (c) 2009-present Facebook.  All rights reserved.
#
"""
This module provides functions for interacting with git commits
created by the apply_diffcamp script.
"""
import re

import gitreview.git as git
import gitreview.git.svn as git_svn

import revision
from exceptions import *

__all__ = ['DiffcampCommit', 'get_dc_commit_chain', 'apply_diff']

# Constants used by diffcamp
SOURCE_CONTROL_SVN = 1
SOURCE_CONTROL_GIT = 2


class DiffcampCommit(object):
    def __init__(self, commit):
        self.commit = commit # a git.commit.Commit object

        # appliedOnto stores the SHA1 value of the commit that the diffcamp
        # diff was applied to.
        #
        # Note that this is often different from the commit's parent(s).
        # For example, say a revision has 3 diffs, and we apply them against
        # trunk.  This would normally create 3 commits, where commit1 is a
        # child of trunk, commit2 is a child of commit1, and commit3 a child of
        # commit2.  However, appliedOnto will be trunk for all 3 commits.
        self.appliedOnto = None

        diff_id_str = self.__findField('DiffCamp Diff')
        try:
            self.diffId = int(diff_id_str)
        except ValueError:
            raise NotADiffcampCommitError(commit, 'invalid diff ID %r' %
                                          (diff_id_str,))

        rev_id_str = self.__findField('DiffCamp Revision')
        try:
            self.revisionId = int(rev_id_str)
        except ValueError:
            raise NotADiffcampCommitError(commit, 'invalid revision ID %r' %
                                          (rev_id_str,))

    def __findField(self, field_name):
        # The diffcamp fields are at the end of the commit message.
        # Search backwards to find the correct version, just in case something
        # else in the commit message happens to match this.
        field_prefix = '\n' + field_name + ': '
        idx = self.commit.comment.rfind(field_prefix)
        if idx < 0:
            raise NotADiffcampCommitError(self.commit,
                                          'no %s field' % (field_name,))

        # The field value is everything up to the next newline:
        end_idx = self.commit.comment.find('\n', idx + 1)

        value = self.commit.comment[idx + len(field_prefix):end_idx]
        return value


def get_dc_commit_chain(repo, rev_id, ref_name=None):
    """
    Get the chain of commits representing the diffs from the specified
    DiffCamp revision.

    Returns a list of commits for this revision, in order from earliest to
    latest.  (I.e. a commit's parent commit always appears before it in the
    list.)
    """
    if ref_name is None:
        # The ref "refs/diffcamp/<rev_id>" points to the most recent
        # commit for this revision.
        #
        # Use this unless another name was explicitly specified.
        ref_name = 'refs/diffcamp/%s' % (rev_id,)

    try:
        commit = repo.getCommit(ref_name)
    except git.NoSuchCommitError:
        # No commits for this revision are available
        return []

    # Attempt to parse the DiffCamp information from the commit message
    try:
        dc_commit = DiffcampCommit(commit)
    except NotADiffcampCommitError, ex:
        # Hmm.  The head of a refs/diffcamp/<NNN> ref really should
        # be a Diffcamp commit.  Just re-raise the NotADiffcampCommitError
        # as-is.
        raise

    # Walk backwards through the commit history until we find a commit that is
    # not from this diffcamp revision.
    commit_chain = [dc_commit]
    while True:
        num_parents = len(commit.parents)
        if num_parents == 0:
            # A little weird, but okay
            break

        # Get the parent commit,
        # Note: We always use the first parent.
        # If a DiffCamp is a merge, the previous commit from the same revision
        # should always be the first parent.
        commit = repo.getCommit(commit.parents[0])

        # Check to see if hte parent looks like a DiffCamp commit.
        try:
            dc_commit = DiffcampCommit(commit)
        except NotADiffcampCommitError:
            # Not a diffcamp commit.  We reached the end of the chain
            break

        # Check to see if this is from the same revision
        if dc_commit.revisionId != rev_id:
            # This is from a different revision.
            # We reached the end of the chain
            break

        # This commit belongs to the same revision.
        # Add it to the chain and continue
        commit_chain.append(dc_commit)

    # Walk over the commits, and set the appliedOnto attribute
    # The first commit was applied onto its parent
    applied_onto = commit_chain[0].commit.parents[0]
    for dc_commit in commit_chain:
      # For all commits but the first, if there is just one parent,
      # the patch was applied onto the same commit as its parent.
      # If there are two commits, the patch was applied onto the second parent.
      #
      # (The first commit should have exactly 1 commit, so this check will
      # always fail for it.)
      if len(dc_commit.commit.parents) > 1:
        applied_onto = dc_commit.commit.parents[1]
      dc_commit.appliedOnto = applied_onto

    # The earlier commits are at the end of the chain,
    # so reverse it before returning.
    commit_chain.reverse()
    return commit_chain


def _compute_patch_paths(repo, diff, apply_to):
    """
    Compute the strip and prefix parameters for git.Repository.applyPatch()
    Returns (strip, prefix)
    """
    if not diff.sourceControlPath:
        # If the diff doesn't have a source control path, we don't have much
        # information to go on.  This shouldn't occur too often.  Most of our
        # diffcamp tools always set sourceControlPath, except when working in a
        # pure git repository.
        #
        # For now, assume strip=0 and no prefix.  (This should be correct for
        # pure git repositories.)
        return (0, None)

    # All of our DiffCamp tools currently set diff.sourceControlPath to a
    # Subversion URL.  Try to find the subversion URL for this repository.
    repo_url = None
    for commit in [apply_to, 'trunk', 'HEAD']:
        try:
            repo_url = git_svn.get_svn_url(repo, apply_to)
            break
        except git.BadCommitError, ex:
            # Ignore BadCommitError.
            # apply_to may be a tree, 'trunk' and 'HEAD' might not exist
            continue

    if not repo_url:
        # Doh.  We couldn't find a SVN url for the current repository.
        # Maybe it's a pure git repo.  Just return strip=0 and no prefix for
        # now.  This might not be correct, though.
        return (0, None)

    # Great, we have both the repo's SVN URL and the diff's URL.
    # We don't really care about the scheme part of the URL, so strip it off
    # of both urls.
    repo_path = repo_url.split('://', 1)[-1]
    diff_path = diff.sourceControlPath.split('://', 1)[-1]

    # Split the path into non-empty components.
    repo_parts = [comp for comp in repo_path.split('/') if comp]
    diff_parts = [comp for comp in diff_path.split('/') if comp]

    # We also don't care if the hostnames don't match (for example, "tubbs" v.
    # "tubbs.facebook.com"), so skip the hostname, too.
    repo_parts = repo_parts[1:]
    diff_parts = diff_parts[1:]

    if len(repo_parts) >= len(diff_parts):
        if repo_parts[:len(diff_parts)] == diff_parts:
            # diff_parts is a prefix of repo_parts.  When applying the diff, we
            # need to strip off the portion of the path that refers to the
            # repository subdirectory.
            #
            # TODO: Ideally we should also make sure that every file in the
            # diff refers to the repository subdirectory.  We should reject an
            # attempt to apply a diff if it affects files not contained in this
            # repository.
            strip = len(repo_parts) - len(diff_parts)
            return (strip, None)
        else:
            # Hmm.  The diff URL and the repository URL don't share a common
            # prefix.
            raise DiffcampGitError('repository SVN url (%s) and diff SVN '
                                   'url (%s) do not match' %
                                   (repo_url, diff.sourceControlPath))
    else:
        if repo_parts == diff_parts[:len(repo_parts)]:
            # repo_parts is a prefix of diff_parts.  We need to add
            # the remainder of diff_parts when applying the diff.
            prefix = '/'.join(diff_parts[len(repo_parts):])
            return (0, prefix)
        else:
            # The diff URL and the repository URL don't share a common prefix.
            raise DiffcampGitError('repository SVN url (%s) and diff SVN '
                                   'url (%s) do not match' %
                                   (repo_url, diff.sourceControlPath))


def apply_diff(repo, diff, apply_to, parents=None, strip=None, prefix=None):
    """
    Create a git commit for a DiffCamp diff.

    apply_to is the git tree-ish to which the patch should be applied to create
    the new tree.

    parents is the list of commits that will be listed as the parents of the
    new commit.  If not specified, [apply_to] will be used.  (However, note
    that this will not work if apply_to refers to a tree and not a commit.)

    Returns the SHA1 hash of the newly creatd commit.
    """
    # TODO: Allow apply_to to be None, in which case attempt to look at the
    # DiffCamp revision info to figure out which commit to apply to.

    rev = diff.revision
    # Get the patch for this diff
    patch = diff.getPatch()

    # Figure out if we need to add a directory prefix to the path names in the
    # patch, or strip off part of the path names.
    if strip is None and prefix is None:
        # automatically try to figure out the correct strip and prefix
        # from the DiffCamp information.
        (strip, prefix) = _compute_patch_paths(repo, diff, apply_to)
    else:
        # One of strip or prefix was specified
        # In this case, if the other one wasn't supplied, use a default value
        # for it.
        if strip is None:
            strip = 0
        if directory is None:
            directory = ''

    # Older versions of diffcamp used to include the "a/" and "b/" prefixes
    # output by "git diff".  Newer versions (created after rE208095) don't.
    # Ideally we should parse the patch to see if it needs this.  For now, just
    # check the date.  This won't be 100% accurate, but is easier to implement
    # for now.
    rE208095_date = 1261036800
    if diff.dateCreated < rE208095_date:
        if diff.sourceControlSystem == SOURCE_CONTROL_GIT:
            strip += 1

    # When diffcamp was changed to strip out the "a/" and "b/" prefixes
    # output by git, it also was changed to strip out "/dev/null" file paths.
    # This results in invalid patches.  Fix this problem.
    patch = re.sub(r'(?m)^(\+\+\+|---) $', r'\1 /dev/null', patch)

    # Apply the patch to create a new tree object
    #
    # git-apply normally rejects the patch if any of the context has changed.
    # Diffcamp diffs have huge amounts of context, which normally means the
    # patch will fail if the file is not exactly identical to the original
    # version.  Use context=5 to tell git-apply to only require matches for the
    # 5 closest context lines around each hunk.
    new_tree = repo.applyPatch(patch, apply_to, strip=strip, prefix=prefix,
                               context=5)

    # Prepare the commit message and author info so we can create a commit
    commit_msg = rev.getCommitMessage()
    # Include the diff ID in the commit message
    commit_msg += 'DiffCamp Diff: %s\n' % (diff.id,)

    if rev.ownerName:
        author_name = rev.ownerName
        author_email = '%s@facebook.com' % (rev.ownerName,)
    else:
        author_name = 'Diffcamp User'
        author_email = 'noreply@facebook.com'
    author_date = str(diff.dateCreated)

    if parents is None:
        parents = [apply_to]

    # Now create the commit
    commit_sha1 = repo.commitTree(new_tree, parents=parents, msg=commit_msg,
                                  author_name=author_name,
                                  author_email=author_email,
                                  author_date=author_date)

    return commit_sha1


class RevisionApplier(object):
    def __init__(self, repo, rev, onto=None, ref_name=None, log=None):
        self.repo = repo
        self.logFile = log

        if isinstance(rev, (int, long)):
            # If the revision argument is a revision ID,
            # get the revision information from diffcamp
            self.rev = revision.get_revision(rev)
        else:
            self.rev = rev

        if ref_name is None:
            self.refName = 'refs/diffcamp/%d' % (self.rev.id,)

        # User-suggested commit against which the diffs should be applied
        self.onto = onto

        # The diffs from this revision that still need to be applied
        self.diffsToApply = []
        # The SHA1 of the current head of self.refName
        self.refHead = None
        # The SHA1 of the commit against which the previous diff was applied
        # This is normally a good indicator of which commit the next patch
        # should be applied.
        self.prevDiffOnto = None

        # Find the existing diffs already in this repository,
        # and update our state accordingly
        self.__findExistingDiffs()

    def log(self, msg):
        if self.logFile is None:
            return
        self.logFile.write(msg)
        self.logFile.write('\n')

    def __findExistingDiffs(self):
        """
        Find the diffs from this revision that have already been applied to
        this repository, and initialize self.diffsToApply, self.refHead, and
        self.prevDiffOnto appropriately.
        """
        # Do nothing for revisions that don't have any diffs yet
        if not self.rev.diffs:
            self.refHead = None
            self.prevDiffOnto = None
            self.diffsToApply = rev.diffs[:]
            return

        # Get the chain of commits already created for diffs from this revision
        dc_commit_chain = get_dc_commit_chain(self.repo, self.rev.id,
                                              self.refName)

        if not dc_commit_chain:
            # If there are no diffs already applied,
            # initialization is very simple
            self.refHead = None
            self.prevDiffOnto = None
            self.diffsToApply = self.rev.diffs[:]
            return

        # The diffcamp ref branch currently points to the last
        # commit in dc_commit_chain
        self.refHead = dc_commit_chain[-1].commit.sha1
        self.prevDiffOnto = dc_commit_chain[-1].appliedOnto

        # Figure out the list of diffs from this revision that still need to be
        # applied.
        #
        # TODO: we could potentially do more validation here; i.e., verify that
        # the commit chain contains an in-order subset of the revision's diffs,
        # starting from the first diff.
        found_last_diff = False
        for diff in self.rev.diffs:
            if found_last_diff:
                self.diffsToApply.append(diff)
            elif diff.id == dc_commit_chain[-1].diffId:
                found_last_diff = True

        if not found_last_diff:
            msg = ('existing commit chain ends with diff %s, '
                   'which doesn\'t seem to be listed in the diffcamp '
                   'diffs for revision %s' %
                   (dc_commit_chain[-1].diffId, self.rev.id))
            raise Exception(msg)

        # Find the commit onto which dc_commit_chain[-1] was applied.
        #
        # dc_commit_chain[0] should have exactly one parent, which is the
        # commit onto which it was applied.  All other commit in the chain
        # either have one parent, in which case they were applied to the same
        # commit as their parent, or two parents, in which cse they were
        # applied to the second parent.
        for dc_commit in reversed(dc_commit_chain[1:]):
            if len(dc_commit.commit.parents) > 1:
                self.prevDiffOnto = dc_commit.commit.parents[1]
                break
        else:
            # We never broke out of the for loop.  The diff was applied
            # to the parent of dc_commit_chain[0].
            if not dc_commit_chain[0].commit.parents:
                # This shouldn't ever happen under normal circumstances.
                # We always have at least 1 parent for diffcamp diffs.
                self.prevDiffOnto = None
            else:
                self.prevDiffOnto = dc_commit_chain[0].commit.parents[0]

    def applyAll(self):
        self.log('  %d diffs to apply' % (len(self.diffsToApply),))
        while self.diffsToApply:
            self.applyNextDiff()

    def applyNextDiff(self):
        diff = self.diffsToApply[0]

        # Compute the list of commits onto which we will try applying this diff
        #
        # TODO: Recent diffs also include a "sourceControlBaseRevision"
        # parameter, containing the svn revision ID or git SHA1 that the diff
        # was computed against.  We should try to prefer this revision if it is
        # valid.  (This unfortunately may not always be useful for git
        # repositories.  For git repositories it might be more useful to have
        # the SHA1 of the tree, rather than of the commit.  We're more likely
        # to have a matching tree ID than commit ID, since the commit also
        # includes the commit date.)
        onto_list = []
        if self.onto:
            onto_list.append(self.onto)
        if self.prevDiffOnto:
            onto_list.append(self.prevDiffOnto)

        # If both self.onto and self.prevDiffOnto fail, then try applying onto
        # refs/remotes/trunk when the diff was created.  If that also fails,
        # try HEAD as a last resort.
        onto_list += ['refs/remotes/trunk@{%s}' % (diff.dateCreated,), 'HEAD']

        success = False
        onto_tried = []
        for onto in onto_list:
            # Resolve this name into a SHA1, to make sure it isn't the same
            # as one of the other commites we already tried.
            try:
                onto_sha1 = self.repo.getCommitSha1(onto)
            except git.NoSuchCommitError, ex:
                self.log('  Attempting to apply diff %s against %r' %
                         (diff.id, onto))
                self.log('    Failed: %s' % (ex,))
                continue

            if onto_sha1 in onto_tried:
                # This is the same as one of the commits we've already tried.
                continue

            onto_tried.append(onto_sha1)
            self.log('  Attempting to apply diff %s against %r' %
                     (diff.id, onto))

            # Compute the parents to use for the new commit
            if self.refHead is None or self.refHead == onto_sha1:
                parents = [onto_sha1]
            else:
                parents = [self.refHead, onto_sha1]

            # Try applying the diff
            try:
                new_commit_sha1 = apply_diff(self.repo, diff, onto, parents)
            except git.PatchFailedError, ex:
                # We failed to apply the patch.
                # Log an error, and continue trying against the next commit
                # in onto_list.
                #
                # Re-indent the error message when logging it.
                indent = '    '
                msg = ('\n' + indent).join(str(ex).splitlines())
                self.log(indent + msg)
                continue

            # Great, it worked
            success = True
            break

        if not success:
            raise git.PatchFailedError('Unable to find a commit where diff %s '
                                       'can be applied' % (diff.id,))

        # Update the ref name.
        reason = ('Applying diffcamp diff %d from revision %d' %
                  (diff.id, self.rev.id,))
        if self.refHead is None:
            old_ref_value = ''
        else:
            old_ref_value = self.refHead
        args = ['update-ref', '-m', reason, '--no-deref', self.refName,
                new_commit_sha1, old_ref_value]
        self.repo.runSimpleGitCmd(args)

        # Update our member variables to prepare for the
        # next diff to be applied
        self.refHead = new_commit_sha1
        self.prevDiffOnto = onto
        self.diffsToApply.pop(0)
