#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
import os
import shutil

import mercurial.hg
import mercurial.match
import mercurial.scmutil
import mercurial.ui

import mercurial.extensions
import mercurial.commands

from ..git.diff import DiffFileList, DiffEntry, Status

import UserDict

class WorkingDirectoryCommit():
    def __str__(self):
        return ':wd'


COMMIT_WD = WorkingDirectoryCommit()
COMMIT_HEAD = '.'


class HgError(Exception):
    pass


class Repository(object):
    def __init__(self, path):
        self.path = path
        # TODO: We should probably define our own custom UI that won't ever
        # print to stdout/stderr.
        self.ui = mercurial.ui.ui()
        mercurial.extensions.loadall(self.ui)
        self.repo = mercurial.hg.repository(self.ui, self.path)

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

        return entries

    def _get_node(self, commit):
        if commit == COMMIT_WD:
            return None
        return mercurial.scmutil.revsingle(self.repo, commit)

    def is_working_dir(self, commit):
        return commit == COMMIT_WD

    def getWorkingDir(self):
        return self.repo.root

    def getCommitSha1(self, name, extra_args=None):
        if name is COMMIT_WD:
            return COMMIT_WD
        node = self._get_node(name)
        if node is None:
            return None
        return node.hex()

    def getBlobContents(self, commit, path, outfile=None):
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


def is_hg_repo(path):
    return os.path.exists(os.path.join(path, '.hg', 'hgrc'))
