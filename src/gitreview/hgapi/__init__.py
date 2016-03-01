#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
import os
import shutil

import mercurial.error
import mercurial.hg
import mercurial.match
import mercurial.scmutil
import mercurial.ui

import mercurial.extensions
import mercurial.commands

from .constants import *
from ..git.diff import DiffFileList, DiffEntry, Status
from ..git.exceptions import NoSuchCommitError

import UserDict


class HgError(Exception):
    pass

# TODO: We should probably override methods that print to stdout/stderr,
# to avoid printing data that would interfere with our user output.
class CustomUI(mercurial.ui.ui):
    def __init__(self, src=None):
        super(CustomUI, self).__init__(src)
        self._gitreview_aliases = {}

    def configitems(self, section, untrusted=False):
        normal_return = super(CustomUI, self).configitems(section, untrusted)
        if section != 'revsetalias':
            return normal_return

        ret = normal_return[:]
        for k, v in self._gitreview_aliases.items():
            ret.append((k, v))
        return ret


class Repository(object):
    def __init__(self, path):
        self.path = path
        self.workingDir = path

        ui = CustomUI()
        # We have to read the local repository config before calling
        # mercurial.extensions.loadall(), in order to figure out what
        # extensions to load.  We need to have loaded all of the correct
        # extensions before trying to create a repository object.
        ui.readconfig(os.path.join(self.path, ".hg", "hgrc"), path)
        mercurial.extensions.loadall(ui)
        self.repo = mercurial.hg.repository(ui, self.path).unfiltered()

    def hasWorkingDirectory(self):
        # Mercurial doesn't have bare repositories
        return True

    def getDiff(self, parent, child, paths=None):
        entries = DiffFileList(parent, child)

        # Find the list of changed nodes.  This is roughly equivalent to
        # "hg status -0 --rev <parent> --rev <child>"
        parent_node = self._get_node(parent)
        child_node = self._get_node(child)

        always_match = mercurial.match.match(self.repo.root,
                                             self.repo.getcwd(), [])
        stat = self.repo.status(parent_node, child_node, always_match,
                                ignored=False, clean=False, unknown=False,
                                listsubrepos=False)
        modified, added, removed, deleted, unknown, ignored, clean = stat

        for path in modified:
            entry = DiffEntry('0644', '0644', '1234', '5678', Status('M'),
                              path, path)
            entries.add(entry)
        for path in added:
            entry = DiffEntry('0000', '0644', '0000', '5678', Status('A'),
                              None, path)
            entries.add(entry)
        for path in removed:
            entry = DiffEntry('0644', '0000', '1234', '0000', Status('D'),
                              path, None)
            entries.add(entry)

        return entries

    def _get_node(self, commit):
        if commit == COMMIT_WD:
            return None
        return mercurial.scmutil.revsingle(self.repo, commit)

    def is_working_dir(self, commit):
        return commit == COMMIT_WD

    def getWorkingDir(self):
        return self.repo.root

    def getCommit(self, name):
        if name is COMMIT_WD:
            # TODO: Support a fake commit object for the working directory,
            # the same way the git API does.
            raise Exception('cannot get a mercurial commit object for the '
                            'working directory')

        try:
            node = self._get_node(name)
        except mercurial.error.HintException:
            # Unfortunately we can get a variety of different exceptions here
            # on lookup error.  (RepoLookupError, RepoError, or even
            # mercurial.error.Abort)
            raise NoSuchCommitError(name)

        return FakeCommit(node)

    def getCommitSha1(self, name, extra_args=None):
        if name is COMMIT_WD:
            return COMMIT_WD
        try:
            node = self._get_node(name)
        except mercurial.error.RepoLookupError:
            raise NoSuchCommitError(name)
        return node.hex()

    def getBlobContents(self, commit, path, outfile=None):
        if hasattr(commit, 'node'):
            # Handle the case if the commit argument
            # is already a mercurial changectx object
            node = commit
        else:
            # Perform a lookup if the commit argument is a string
            node = self._get_node(commit)

        if node is None:
            full_path = os.path.abspath(os.path.join(self.repo.root, path))
            sub_path = os.path.relpath(full_path, self.repo.root)
            if sub_path.split(os.sep)[0] == '..':
                raise Exception('cannot specify a path outside of the '
                                'repository')

            with open(full_path, 'r') as f:
                if outfile is None:
                    return f.read()
                shutil.copyfileobj(f, outfile)
        else:
            filenode = node[path]
            if outfile is None:
                return filenode.data()
            else:
                outfile.write(filenode.data())

        if outfile is not None:
            outfile.flush()

    def getRefNames(self):
        # FIXME
        return []

    def listTree(self, commit, dirname):
        # FIXME
        return []

    def isRevision(self, name):
        try:
            self.repo[name]
            return True
        except Exception as ex:
            return False


class TreeEntry(object):
    def __init__(self, name, mode, type, sha1):
        self.name = name
        self.mode = mode
        self.type = type
        self.sha1 = sha1

    def __str__(self):
        return self.name

    def __repr__(self):
        return 'TreeEntry(%r, %r, %r, %r)' % (self.name, self.mode, self.type,
                                              self.sha1)


class FakeCommit(object):
    '''
    FakeCommit provides an API similar to git.commit.Commit
    '''
    def __init__(self, node):
        self.node = node

    @property
    def parents(self):
        return [FakeCommit(p) for p in self.node.parents()]

    @property
    def comment(self):
        return self.node.description()

    def __str__(self):
        return self.node.hex()


def is_hg_repo(path):
    return os.path.exists(os.path.join(path, '.hg', 'hgrc'))
