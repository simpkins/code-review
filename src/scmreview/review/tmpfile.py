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
import abc
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Optional, Type


class FileAPI(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def open(self) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def __enter__(self) -> "TmpFile":
        raise NotImplementedError()

    @abc.abstractmethod
    def __exit__(
        self,
        exc_type: Type[BaseException],
        exc_value: BaseException,
        traceback: types.TracebackType,
    ) -> bool:
        raise NotImplementedError()

    @abc.abstractmethod
    def __str__(self) -> str:
        raise NotImplementedError()


class TmpFile(FileAPI):
    def __init__(self, repo, commit, path):
        self.repo = repo
        self.commit = commit
        self.path = path
        self.tmp_file = None

    def open(self) -> None:
        if self.repo.is_working_dir(self.commit):
            working_dir = self.repo.get_working_dir()
            if working_dir is None:
                raise Exception(
                    "cannot diff the working directory in a bare repository"
                )
            self.tmp_path = working_dir / self.path
        else:
            username = os.environ.get("USER") or os.environ.get("USERNAME")
            prefix = "scm-review-%s-" % (username,)
            suffix = "-" + os.path.basename(self.path)
            # Note that we have to use delete=False on Windows, and manually
            # delete the file ourselves.  Without delete=False other programs
            # (e.g., the editor or diff viewer) will get permission denied
            # errors when trying to view the file.
            self.tmp_file = tempfile.NamedTemporaryFile(
                prefix=prefix, suffix=suffix, delete=False
            )
            self.tmp_path = Path(self.tmp_file.name)
            # Invoke git to write the blob contents into the temporary file
            self.repo.getBlobContents(self.commit, self.path, outfile=self.tmp_file)

    def __enter__(self) -> "TmpFile":
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException],
        exc_value: BaseException,
        traceback: types.TracebackType,
    ) -> bool:
        if self.tmp_file:
            self.tmp_file.close()
            self.tmp_path.unlink()

        return False

    def __str__(self) -> str:
        return str(self.tmp_path)


if sys.platform != "win32":

    class EmptyFile(FileAPI):
        def __init__(self) -> None:
            pass

        def open(self) -> None:
            pass

        def __enter__(self) -> "TmpFile":
            return self

        def __exit__(
            self,
            exc_type: Type[BaseException],
            exc_value: BaseException,
            traceback: types.TracebackType,
        ) -> bool:
            return False

        def __str__(self) -> str:
            return "/dev/null"

else:

    class EmptyFile(FileAPI):
        def __init__(self) -> None:
            self.tmp_file: Optional[tempfile.NamedTemporaryFile] = None

        def open(self) -> None:
            username = os.environ.get("USER") or os.environ.get("USERNAME")
            prefix = f"scm-review-{username}-"
            suffix = "-empty"
            self.tmp_file = tempfile.NamedTemporaryFile(
                prefix=prefix, suffix=suffix, delete=False
            )

        def __enter__(self) -> "TmpFile":
            return self

        def __exit__(
            self,
            exc_type: Type[BaseException],
            exc_value: BaseException,
            traceback: types.TracebackType,
        ) -> bool:
            if self.tmp_file:
                tmp_path = self.tmp_file.name
                self.tmp_file.close()
                os.unlink(tmp_path)

            return False

        def __str__(self) -> str:
            return self.tmp_file.name
