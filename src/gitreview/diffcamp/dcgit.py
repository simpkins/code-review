#!/usr/bin/python -tt
#
# Copyright (c) 2009-present Facebook.  All rights reserved.
#
import gitreview.git as git


class DiffcampGitError(Exception):
    pass


class NotADiffcampCommitError(DiffcampGitError):
    def __init__(self, commit, reason):
        DiffcampGitError.__init__(self)
        self.commit = commit
        self.reason = reason

    def __str__(self):
        return ('%.7s is not a DiffCamp commit: %s' %
                (self.commit.sha1, self.reason))


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

        diff_id_str = self.__findField('Differential Diff')
        try:
            self.diffId = int(diff_id_str)
        except ValueError:
            raise NotADiffcampCommitError(commit, 'invalid diff ID %r' %
                                          (diff_id_str,))

        rev_id_str = self.__findField('Differential Revision')
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
    differential revision.

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

    # Attempt to parse the differential information from the commit message
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
        # If a differential commit is a merge, the previous commit from the
        # same revision should always be the first parent.
        commit = repo.getCommit(commit.parents[0])

        # Check to see if hte parent looks like a differential commit.
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
