#!/usr/bin/python -tt
#
# Copyright 2009-2010 Facebook, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

import os
from typing import Optional

import scmreview.git as git

from .exceptions import *
from . import cli_reviewer
from . import tmpfile

CliReviewer = cli_reviewer.CliReviewer


def sort_reasonably(entries):
    def get_key(entry):
        path = entry.getPath()
        (main, ext) = os.path.splitext(path)

        # Among files with the same base name but different extensions,
        # use the following priorities for sorting:
        if ext == ".thrift":
            priority = 10
        elif ext == ".h" or ext == ".hpp" or ext == ".hh" or ext == ".H":
            priority = 20
        elif ext == ".c" or ext == ".cpp" or ext == ".cc" or ext == ".C":
            priority = 30
        else:
            priority = 40

        return "%s_%s_%s" % (main, priority, ext)

    entries.sort(key=get_key)


class Review(object):
    def __init__(self, repo, diff):
        self.repo = repo
        self.diff = diff

        self.commit_aliases = {}
        self.set_commit_alias("parent", self.diff.parent)
        self.set_commit_alias("child", self.diff.child)

        self.current_index = 0

        # Assign a fixed ordering to the file list
        #
        # TODO: read user-specified file orderings in the future
        self.ordering = []
        for entry in self.diff:
            self.ordering.append(entry)

        sort_reasonably(self.ordering)
        self.num_entries = len(self.ordering)

    def get_entries(self):
        # XXX: we return a shallow copy.
        # Callers shouldn't modify the returned value directly
        # (we could return a copy if we really don't trust our callers)
        return self.ordering

    def get_num_entries(self):
        return len(self.ordering)

    def get_current_entry(self):
        try:
            return self.ordering[self.current_index]
        except IndexError:
            # This happens when the diff is empty
            raise NoCurrentEntryError()

    def get_entry(self, index):
        return self.ordering[index]

    def has_next(self):
        return self.current_index + 1 < self.num_entries

    def next(self):
        if not self.has_next():
            raise IndexError(self.current_index)
        self.current_index += 1

    def prev(self):
        if self.current_index == 0:
            raise IndexError(-1)
        self.current_index -= 1

    def goto(self, index):
        if index < 0 or index >= self.num_entries:
            raise IndexError(index)
        self.current_index = index

    def get_file(self, commit: str, path: Optional[str]) -> tmpfile.TmpFile:
        expanded_commit = self.expand_commit_name(commit)

        if path == None:
            # This happens if the user tries to view the child version
            # of a deleted file, or the parent version of a new file.
            raise git.NoSuchBlobError("%s:<None>" % (commit,))

        try:
            return tmpfile.TmpFile(self.repo, expanded_commit, path)
        except (git.NoSuchBlobError, git.NotABlobError) as ex:
            # For user-friendliness,
            # change the name in the exception to the unexpanded name
            ex.name = "%s:%s" % (commit, path)
            raise

    def is_revision_or_path(self, name):
        """
        Like git.repo.isRevisionOrPath(), but handles commit aliases too.
        """
        # Try expanding commit aliases in the name, and seeing if that is
        # a valid commit.
        is_rev = self.repo.isRevision(self.expand_commit_name(name))
        working_dir = self.repo.get_working_dir()
        if working_dir is not None:
            is_path = (working_dir / name).exists()
        else:
            is_path = None

        if is_rev and is_path:
            reason = "both revision and filename"
            raise git.AmbiguousArgumentError(name, reason)
        elif is_rev:
            return True
        elif is_path:
            return False
        else:
            reason = "unknown revision or path not in the working tree"
            raise git.AmbiguousArgumentError(name, reason)

    def get_commit_aliases(self):
        return self.commit_aliases.keys()

    def set_commit_alias(self, alias, commit):
        # Expand any aliases in the alias name before we store it
        expanded_commit = self.expand_commit_name(commit)

        # Fully expand the commit name to a SHA1
        sha1 = self.repo.getCommitSha1(expanded_commit)

        self.commit_aliases[alias] = sha1

    def unset_commit_alias(self, alias):
        del self.commit_aliases[alias]

    def expand_commit_name(self, name):
        return self.repo.expand_commit_name(name, self.commit_aliases)
