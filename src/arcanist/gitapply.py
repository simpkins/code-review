#!/usr/local/bin/python2.6 -tt
#
# Copyright 2004-present Facebook.  All rights reserved.
#
import re
import time

from . import revision

from .gitreview.diffcamp.dcgit import get_dc_commit_chain
from .gitreview import git
from .gitreview.git import svn as git_svn


def _compute_patch_paths(repo, diff, apply_to):
    """
    Compute the strip and prefix parameters for git.Repository.applyPatch()
    Returns (strip, prefix)
    """
    if not diff.src_control_path:
        # If the diff doesn't have a source control path, we don't have much
        # information to go on.  This shouldn't occur too often.  Most of our
        # diffcamp tools always set src_control_path, except when working in a
        # pure git repository.
        #
        # For now, assume strip=1 and no prefix.  (This should be correct for
        # pure git repositories.)
        return (1, None)

    # All of our DiffCamp tools currently set diff.src_control_path to a
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
        # Maybe it's a pure git repo.  Just return strip=1 and no prefix for
        # now.  This might not be correct, though.
        return (1, None)

    # Great, we have both the repo's SVN URL and the diff's URL.
    # We don't really care about the scheme part of the URL, so strip it off
    # of both urls.
    repo_path = repo_url.split('://', 1)[-1]
    diff_path = diff.src_control_path.split('://', 1)[-1]

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
            strip = 1 + len(repo_parts) - len(diff_parts)
            return (strip, None)
        else:
            # Hmm.  The diff URL and the repository URL don't share a common
            # prefix.
            raise DiffcampGitError('repository SVN url (%s) and diff SVN '
                                   'url (%s) do not match' %
                                   (repo_url, diff.src_control_path))
    else:
        if repo_parts == diff_parts[:len(repo_parts)]:
            # repo_parts is a prefix of diff_parts.  We need to add
            # the remainder of diff_parts when applying the diff.
            prefix = '/'.join(diff_parts[len(repo_parts):])
            return (1, prefix)
        else:
            # The diff URL and the repository URL don't share a common prefix.
            raise DiffcampGitError('repository SVN url (%s) and diff SVN '
                                   'url (%s) do not match' %
                                   (repo_url, diff.src_control_path))


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
    patch = diff.get_patch()

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
    commit_msg = rev.get_commit_message()
    # Include the diff ID in the commit message
    commit_msg += 'Differential Diff: %s\n' % (diff.id,)

    # TODO: extract the author name and email address from the author PHID
    author_name = 'Differential User'
    author_email = 'noreply@fb.com'

    # TODO: phabricator differential doesn't report the date created
    # via a conduit API.
    #author_date = str(diff.dateCreated)
    author_date = str(time.time())

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
        self.log_file = log

        if isinstance(rev, (int, long)):
            # If the revision argument is a revision ID,
            # get the revision information from diffcamp
            self.rev = revision.get_revision(repo.workingDir, rev)
        else:
            self.rev = rev

        if ref_name is None:
            self.ref_name = 'refs/diffcamp/%d' % (self.rev.id,)

        # User-suggested commit against which the diffs should be applied
        self.onto = onto

        # The diffs from this revision that still need to be applied
        self.diffs_to_apply = []
        # The SHA1 of the current head of self.ref_name
        self.ref_head = None
        # The SHA1 of the commit against which the previous diff was applied
        # This is normally a good indicator of which commit the next patch
        # should be applied.
        self.prev_diff_onto = None

        # Find the existing diffs already in this repository,
        # and update our state accordingly
        self.__find_existing_diffs()

    def log(self, msg):
        if self.log_file is None:
            return
        self.log_file.write(msg)
        self.log_file.write('\n')

    def __find_existing_diffs(self):
        """
        Find the diffs from this revision that have already been applied to
        this repository, and initialize self.diffs_to_apply, self.ref_head, and
        self.prev_diff_onto appropriately.
        """
        # Do nothing for revisions that don't have any diffs yet
        if not self.rev.diffs:
            self.ref_head = None
            self.prev_diff_onto = None
            self.diffs_to_apply = rev.diffs[:]
            return

        # Get the chain of commits already created for diffs from this revision
        dc_commit_chain = get_dc_commit_chain(self.repo, self.rev.id,
                                              self.ref_name)

        if not dc_commit_chain:
            # If there are no diffs already applied,
            # initialization is very simple
            self.ref_head = None
            self.prev_diff_onto = None
            self.diffs_to_apply = self.rev.diffs[:]
            return

        # The diffcamp ref branch currently points to the last
        # commit in dc_commit_chain
        self.ref_head = dc_commit_chain[-1].commit.sha1
        self.prev_diff_onto = dc_commit_chain[-1].appliedOnto

        # Figure out the list of diffs from this revision that still need to be
        # applied.
        #
        # TODO: we could potentially do more validation here; i.e., verify that
        # the commit chain contains an in-order subset of the revision's diffs,
        # starting from the first diff.
        found_last_diff = False
        for diff in self.rev.diffs:
            if found_last_diff:
                self.diffs_to_apply.append(diff)
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
                self.prev_diff_onto = dc_commit.commit.parents[1]
                break
        else:
            # We never broke out of the for loop.  The diff was applied
            # to the parent of dc_commit_chain[0].
            if not dc_commit_chain[0].commit.parents:
                # This shouldn't ever happen under normal circumstances.
                # We always have at least 1 parent for diffcamp diffs.
                self.prev_diff_onto = None
            else:
                self.prev_diff_onto = dc_commit_chain[0].commit.parents[0]

    def apply_all(self):
        self.log('  %d diffs to apply' % (len(self.diffs_to_apply),))
        while self.diffs_to_apply:
            self.apply_next_diff()

    def apply_next_diff(self):
        diff = self.diffs_to_apply[0]

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
        if self.prev_diff_onto:
            onto_list.append(self.prev_diff_onto)


        # TODO: The old diffcamp code used to report when a diff was created.
        # We could use this as a guess for which version of trunk to apply
        # onto.  We should fix phabricator differential so it also reports the
        # date.
        #
        # TODO: It would be nice to use diff.src_control_base_revision, if it
        # exists in this repository.
        if False:
            # If both self.onto and self.prev_diff_onto fail, then try applying
            # onto refs/remotes/trunk when the diff was created.  If that also
            # fails, try HEAD as a last resort.
            onto_list.append('refs/remotes/trunk@{%s}' % (diff.date_created,))
        onto_list.append('HEAD')

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
            if self.ref_head is None or self.ref_head == onto_sha1:
                parents = [onto_sha1]
            else:
                parents = [self.ref_head, onto_sha1]

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
        if self.ref_head is None:
            old_ref_value = ''
        else:
            old_ref_value = self.ref_head
        args = ['update-ref', '-m', reason, '--no-deref', self.ref_name,
                new_commit_sha1, old_ref_value]
        self.repo.runSimpleGitCmd(args)

        # Update our member variables to prepare for the
        # next diff to be applied
        self.ref_head = new_commit_sha1
        self.prev_diff_onto = onto
        self.diffs_to_apply.pop(0)
