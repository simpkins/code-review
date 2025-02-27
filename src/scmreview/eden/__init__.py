#!/usr/bin/python -tt
#
# Copyright (c) Facebook, Inc. and its affiliates
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
from __future__ import absolute_import, division, print_function

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from scmreview.scm.repo import RepositoryBase
from ..git.diff import BlobInfo, DiffFileList, DiffEntry, Status


class Repository(RepositoryBase):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.eden_cmd = ["hg"]
        self.env = os.environ.copy()
        self.env["HGPLAIN"] = "1"
        # Allow resolving user-defined revset aliases
        self.env["HGPLAINEXCEPT"] = "revsetalias"

        self._node_cache: Dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def get_working_dir(self) -> Optional[Path]:
        return self.path

    def get_default_diff_endpoints(self) -> Tuple[str, str]:
        raise (COMMIT_HEAD, COMMIT_WD)

    def get_head_commit_name(self) -> str:
        return COMMIT_HEAD

    def get_working_dir_diff_name(self) -> str:
        return COMMIT_WD

    def getDiff(self, parent, child, paths=None):
        cmd = ["status", "-0Cmardu"]
        if child == COMMIT_WD:
            if parent == COMMIT_WD:
                return DiffFileList("", "")
                return entries
            cmd += ["--rev", parent]
        elif parent == COMMIT_WD:
            cmd += ["--rev", self._get_node(parent)]
            cnode = self._get_node(child)
            # TODO: reverse statuses
            raise Exception("todo: reverse each file status after diff")
        else:
            parent = self._get_node(parent)
            child = self._get_node(child)
            cmd += ["--rev", parent, "--rev", child]

        out = self.run_cmd(cmd)
        entries = DiffFileList(parent, child)
        DiffParser(entries, out).run()
        return entries

    def expand_commit_name(self, name, aliases):
        # COMMIT_WD isn't a string, and points to fake WorkingDirectoryCommit
        # objects.  We have to handle it specially.
        if name == COMMIT_WD or name == COMMIT_WD_STR:
            return COMMIT_WD

        # Do an explicit lookup in aliases first, to handle aliases
        # which point to a WorkingDirectoryCommit object.  We don't allow
        # these aliases to be used in more complicated revset expressions,
        # since these expressions don't make sense.
        ret = aliases.get(name)
        if ret is not None:
            return ret

        real_aliases = dict(
            (n, v)
            for n, v in aliases.items()
            if not isinstance(v, WorkingDirectoryCommit)
        )

        name = self._prevent_revnum(name)
        cmd = ["log", "-T{node}\n", "-r", name]
        for n, v in aliases.items():
            cmd.append("--config")
            cmd.append("revsetalias.%s=%s" % (n, v))

        out = self.run_oneline(cmd)
        return out.decode("utf-8")

    def isRevision(self, name):
        if name == COMMIT_WD:
            return True

        try:
            self._get_node(name)
            return True
        except Exception:
            return False

    def is_working_dir(self, commit):
        return commit == COMMIT_WD

    def getCommitSha1(self, name, extra_args=None):
        if name is COMMIT_WD:
            return COMMIT_WD

        return self._get_node(name)

    def getBlobContents(self, commit, path, outfile=None):
        cmd = ["cat", "-r", commit, "path:" + path]

        if outfile is None:
            return self.run_cmd(cmd)
        else:
            self.run_cmd(cmd, stdout=outfile)

    def _get_node(self, name: str) -> str:
        result = self._node_cache.get(name)
        if result is not None:
            return result

        name = self._prevent_revnum(name)

        out = self.run_oneline(["log", "-T{node}", "-r", name])
        result = out.decode("utf-8")
        self._node_cache[name] = result
        return result

    def run_cmd(self, cmd, stdout=subprocess.PIPE):
        full_cmd = self.eden_cmd + cmd
        start = time.time()
        logging.debug(f"run hg cmd: {full_cmd}")
        p = subprocess.Popen(
            full_cmd, env=self.env, cwd=self.path, stdout=stdout, stderr=subprocess.PIPE
        )
        out, err = p.communicate()
        duration = time.time() - start
        logging.debug(
            f"  --> hg {cmd[0]} returned {p.returncode} in {duration} seconds"
        )
        if p.returncode != 0:
            raise Exception("error running %r: stderr=%r" % (cmd, err))
        return out

    def run_oneline(self, cmd):
        out = self.run_cmd(cmd)
        lines = out.splitlines()
        if len(lines) != 1:
            raise Exception(
                "expected command %r to produce a single line, got %r" % (cmd, out)
            )
        return lines[0]

    def _prevent_revnum(self, revset: str) -> str:
        # Attempt to wrap integers in the input in "id()"
        #
        # This prevents Eden SCM from treating it as a old-style revnum.
        # revnum resolution is disabled by default in most cases, but is
        # enabled when HGPLAIN=1 is set in the environment.  We don't ever
        # want to use revnum resolution, since this produces different results
        # than what users normally get when running hg without HGPLAIN=1

        # For now we only handle input that looks like a single number, or a
        # number followed by "^"
        if revset.endswith("^"):
            return self._prevent_revnum(revset[:-1]) + "^"

        try:
            int(revset)
            return f"id({revset})"
        except ValueError:
            pass

        return revset


DIFF_CODE_SPACE = ord(b" ")
DIFF_CODE_MODIFIED = ord(b"M")
DIFF_CODE_ADDED = ord(b"A")
DIFF_CODE_REMOVED = ord(b"R")
DIFF_CODE_DELETED = ord(b"!")
DIFF_CODE_UNKNOWN = ord(b"?")
DIFF_CODE_IGNORED = ord(b"I")
DIFF_CODE_CLEAN = ord(b"C")


class DiffParser(object):
    def __init__(self, results: DiffFileList, data: bytes) -> None:
        self.results = results
        self.data = data
        self.idx = 0
        self._old_paths: Set[bytes] = set()
        self.prev_entry: Optional[DiffEntry] = None

    def run(self) -> None:
        data_len = len(self.data)
        while self.idx < data_len:
            end = self.parse_next()
            self.idx = end + 1
        self.finish_prev_entry()

    def parse_next(self) -> int:
        idx = self.idx
        end = self.data.find(b"\0", idx)
        if end == -1:
            raise Exception(
                "unfinished entry at end of diff output: " f"{self.data[idx:]!r}"
            )
        if end - idx < 3:
            raise Exception(f"unparsable diff entry: {self.data[idx:end]!r}")

        code = self.data[idx]
        if self.data[idx + 1] != DIFF_CODE_SPACE:
            raise Exception(f"unparsable diff entry: {self.data[idx:end]!r}")
        path = self.data[idx + 2 : end]
        self.parse_entry(code, path)
        return end

    def finish_prev_entry(self) -> None:
        if self.prev_entry is not None:
            self.results.add(self.prev_entry)
            self.prev_entry = None

    def parse_entry(self, code: int, path: bytes) -> None:
        if code == DIFF_CODE_SPACE:
            if self.prev_entry is None:
                raise Exception(f"diff entry is missing status code: {path!r}")

            self._old_paths.add(path)
            self.prev_entry.status = Status(b"R")
            self.prev_entry.old = BlobInfo(sha1=b"", path=path, mode=b"0644")
            self.finish_prev_entry()
            return

        self.finish_prev_entry()

        diff_path: Optional[bytes] = path
        old_path: Optional[bytes] = None
        if code == DIFF_CODE_MODIFIED:
            status = Status(b"M")
            old_path = path
        elif code == DIFF_CODE_ADDED:
            status = Status(b"A")
        elif code in (DIFF_CODE_REMOVED, DIFF_CODE_DELETED):
            # In practice removed entries are always listed after all added &
            # modified entries, so we should have already put all known old
            # paths in self._old_paths by now
            if path in self._old_paths:
                # This path was moved away from, and we already added
                # a DiffEntry for it using the new path.
                return
            status = Status(b"D")
            old_path = path
            diff_path = None
        elif code in (DIFF_CODE_UNKNOWN, DIFF_CODE_IGNORED, DIFF_CODE_CLEAN):
            return
        else:
            raise Exception(f"unexpected diff entry: ({code!r}, {path!r})")

        # TODO: these are dummy values.
        # We should perhaps change to our our own custom DiffEntry type for
        # EdenSCM that does not contain these fields.
        old_mode = b"0000"
        old_sha1 = b""
        new_mode = b"0000"
        new_sha1 = b""
        self.prev_entry = DiffEntry(
            old_mode, new_mode, old_sha1, new_sha1, status, old_path, diff_path
        )


class WorkingDirectoryCommit:
    def __str__(self):
        return COMMIT_WD_STR


COMMIT_WD = WorkingDirectoryCommit()
COMMIT_WD_STR = ":wd"
COMMIT_HEAD = "."
