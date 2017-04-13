#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#
import os
import shutil
import stat

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
from ..git.obj import TreeEntry

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
        self._manifestCache = {}

        if hasattr(CustomUI, 'load'):
            # Ick.  Mercurial has changed its API recently.
            # New versions of mercurial require using ui.load() to load configs
            # properly.
            ui = CustomUI.load()
        else:
            # Older versions of mercurial didn't have ui.load() and the
            # normal constructor load all configs.
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

    def hg_path(self, path, *extra):
        '''
        Get the path to a file in the .hg directory.

        If this is a shared working copy, this returns the path in the main .hg
        directory rather than the shim .hg directory associated with this
        working copy.
        '''
        if self.repo.shared():
            return os.path.join(self.repo.sharedpath, path, *extra)
        return self.repo.vfs.join(path, *extra)

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

        old_paths = set()

        def process_entry(path, old_path):
            if old_path is None:
                status = Status('A')
                old_mode = '0000'
                old_sha1 = '0000'  # dummy value
            else:
                status = Status('M')
                old_mode = '0644'  # TODO: get the correct mode data
                old_sha1 = '1234'  # dummy value

            if child_node is not None:
                rename_info = child_node[path].renamed()
                new_sha1 = '5678'  # TODO: get the filectx ID
            else:
                # TODO: get rename info for working directory changes
                # TODO: use a workingctx() object
                rename_info = None
                new_sha1 = '5678'  # TODO

            if rename_info:
                status = Status('R')
                old_path = rename_info[0]
                old_paths.add(old_path)
                old_mode = '0644'  # TODO: get the correct mode data
                old_sha1 = '1234'  # dummy value

            new_mode = '0644'  # TODO: get the correct mode value

            entry = DiffEntry(old_mode, new_mode, old_sha1, new_sha1, status,
                              old_path, path)
            entries.add(entry)

        for path in modified:
            process_entry(path, path)

        for path in added:
            process_entry(path, None)

        for path in removed:
            if path in old_paths:
                # This path was moved away from, and we already added
                # a DiffEntry for it above.
                continue
            entry = DiffEntry('0644', '0000', '1234', '0000', Status('D'),
                              path, None)
            entries.add(entry)

        return entries

    def _get_node(self, commit):
        if commit == COMMIT_WD:
            return None
        try:
            return mercurial.scmutil.revsingle(self.repo, commit)
        except (mercurial.error.RepoError, mercurial.error.Abort):
            # Unfortunately we can get a variety of different exceptions here
            # on lookup error.  (RepoLookupError, RepoError, or even
            # mercurial.error.Abort)
            raise NoSuchCommitError(commit)

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

        node = self._get_node(name)
        return FakeCommit(node)

    def getCommitSha1(self, name, extra_args=None):
        if name is COMMIT_WD:
            return COMMIT_WD
        node = self._get_node(name)
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
        if dirname:
            dirname = os.path.normpath(dirname)
        if dirname == '.':
            dirname = ''

        if commit == COMMIT_WD:
            # Complete based on the working directory contents
            results = []
            path = os.path.join(self.path, dirname)
            for entry in os.listdir(path):
                st = os.lstat(os.path.join(path, entry))
                if stat.S_ISDIR(st.st_mode):
                    type = 'tree'
                else:
                    type = 'blob'
                entry = TreeEntry(entry, mode=st.st_mode, type=type, sha1=None)
                results.append(entry)
            return results

        # Mercurial's data structures are unfortunately pretty lame.
        # It doesn't have subdirectory data, just a giant flat list of all of
        # the files in the repository.  This is really slow to work with in
        # large repositories.
        #
        # We convert the giant flat list into a subdirectory structure.
        # This is slow the first time we have to do it, but we cache the
        # results for subsequent calls.
        node = self._get_node(commit)
        trees = self._manifestCache.get(node.hex())
        if trees is None:
            trees = self._parseManifest(node.manifest())
            self._manifestCache[node.hex()] = trees

        result = trees.get(dirname, [])
        return trees.get(dirname, [])

    def _parseManifest(self, manifest):
        '''
        Convert a mercurial manifest into a dictionary of tree-like objects.
        '''
        current_dir = ''
        dir_stack = [('', [])]
        complete_dirs = {}

        for path, path_node_id, flags in manifest.iterentries():
            #print('path %r' % (path,))
            idx = path.rfind('/') + 1
            dir = path[:idx]
            base = path[idx:]

            if flags == 'x':
                mode = 0o755
            else:
                mode = 0o644
            entry = TreeEntry(base, mode=mode, type='blob', sha1=None)

            if dir == dir_stack[-1][0]:
                #print('  append %r -> %r' % (dir, base))
                #assert entry.name not in [e.name for e in dir_stack[-1][1]]
                dir_stack[-1][1].append(entry)
                continue

            # Pull back as many trailing directories off of dir and dir_stack
            # until we find a common ancestor.  This may be dir_stack itself
            while True:
                while len(dir_stack[-1][0]) > idx:
                    #print('  pop_stack %r' % (dir_stack[-1][0],))
                    dir_path, dir_entries = dir_stack.pop()
                    complete_dirs[dir_path[:-1]] = dir_entries
                while idx > len(dir_stack[-1][0]):
                    #print('  pop_path %r' % (path[:idx],))
                    idx = path.rfind('/', 0, idx - 1) + 1
                if idx == len(dir_stack[-1][0]):
                    if path[:idx] == dir_stack[-1][0]:
                        #print('  match at %r' % (path[:idx],))
                        break
                    else:
                        # The dir stack and dir portion of the path are both
                        # the same length, but are different.  Pop an entry off
                        # each before continuing around the loop.
                        #print('  pop_stack %r' % (dir_stack[-1][0],))
                        dir_path, dir_entries = dir_stack.pop()
                        complete_dirs[dir_path[:-1]] = dir_entries
                        #print('  pop_path %r' % (path[:idx],))
                        idx = path.rfind('/', 0, idx - 1) + 1

            # Now push new entries on the stack
            while True:
                next_idx = path.find('/', idx)
                if next_idx < 0:
                    base = path[idx:]
                    #print('  add_file %r --> %r' % (dir_stack[-1][0], base,))
                    #assert base == os.path.basename(path)
                    #if os.path.dirname(path):
                    #    assert dir_stack[-1][0] == os.path.dirname(path) + '/'
                    #else:
                    #    assert dir_stack[-1][0] == ''
                    #assert entry.name not in [e.name for e in dir_stack[-1][1]]
                    dir_stack[-1][1].append(entry)
                    break
                else:
                    dir_base = path[idx:next_idx]
                    dir_entry = TreeEntry(dir_base, mode=0o755, type='tree',
                                          sha1=None)
                    #print('  add_dir %r --> %r' % (dir_stack[-1][0], dir_base))
                    #assert dir_stack[-1][0] == path[:idx]
                    #assert dir_base not in [e.name for e in dir_stack[-1][1]]
                    dir_stack[-1][1].append(dir_entry)
                    dir_name = path[:next_idx + 1]
                    #print('  push_stack %r' % (dir_name,))
                    dir_stack.append((dir_name, []))
                    idx = next_idx + 1

        while dir_stack:
            path, dir_entry = dir_stack.pop()
            if path:
                complete_dirs[path[:-1]] = dir_entry
            else:
                complete_dirs[''] = dir_entry

        return complete_dirs

    def isRevision(self, name):
        try:
            self.repo[name]
            return True
        except Exception as ex:
            return False


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
    # Mercurial only checks if .hg exists and is a directory.
    # The contents inside .hg may be quite different depending on the
    # extensions being used.
    return os.path.isdir(os.path.join(path, '.hg'))
