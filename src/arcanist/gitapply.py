#!/usr/local/bin/python2.6 -tt
#
# Copyright 2004-present Facebook.  All rights reserved.
#
import re
import time


def _compute_patch_paths(repo, diff, apply_to):
    """
    Compute the strip and prefix parameters for git.Repository.applyPatch()
    Returns (strip, prefix)
    """
    # TODO: We used to have logic here that worked a really long time ago,
    # but phabricator has changed how it returns this information over time.
    #
    # We probably need to update this to make use of the diff.repo_path_prefix
    # parameter now set by the code in arcanist/apply_diffs.py
    return (1, None)


def apply_diff(repo, diff, apply_to, parents=None, strip=None, prefix=None):
    """
    Create a git commit for a phabricator diff.

    apply_to is the git tree-ish to which the patch should be applied to create
    the new tree.

    parents is the list of commits that will be listed as the parents of the
    new commit.  If not specified, [apply_to] will be used.  (However, note
    that this will not work if apply_to refers to a tree and not a commit.)

    Returns the SHA1 hash of the newly creatd commit.
    """
    # TODO: Allow apply_to to be None, in which case attempt to look at the
    # phabricator revision info to figure out which commit to apply to.

    rev = diff.revision
    # Get the patch for this diff
    patch = diff.get_patch()

    # Figure out if we need to add a directory prefix to the path names in the
    # patch, or strip off part of the path names.
    if strip is None and prefix is None:
        # automatically try to figure out the correct strip and prefix
        # from the phabricator information.
        (strip, prefix) = _compute_patch_paths(repo, diff, apply_to)
    else:
        # One of strip or prefix was specified
        # In this case, if the other one wasn't supplied, use a default value
        # for it.
        if strip is None:
            strip = 0
        if directory is None:
            directory = ''

    # When phabricator was changed to strip out the "a/" and "b/" prefixes
    # output by git, it also was changed to strip out "/dev/null" file paths.
    # This results in invalid patches.  Fix this problem.
    patch = re.sub(r'(?m)^(\+\+\+|---) $', r'\1 /dev/null', patch)

    # Apply the patch to create a new tree object
    #
    # git-apply normally rejects the patch if any of the context has changed.
    # phabricator diffs have huge amounts of context, which normally means the
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
