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
import types
from pathlib import Path
from typing import BinaryIO, Optional, Type


class RepositoryBase(abc.ABC):
    def __enter__(self) -> "RepositoryBase":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        tb: Optional[types.TracebackType],
    ) -> bool:
        return False

    @abc.abstractmethod
    def getDiff(self, parent, child, paths=None):
        raise NotImplementedError()

    @abc.abstractmethod
    def expand_commit_name(self, name, aliases):
        raise NotImplementedError()

    @abc.abstractmethod
    def getCommitSha1(self, name, extra_args=None):
        raise NotImplementedError()

    @abc.abstractmethod
    def is_working_dir(self, commit):
        raise NotImplementedError()

    @abc.abstractmethod
    def getBlobContents(
        self, commit, path, outfile: Optional[BinaryIO] = None
    ) -> bytes:
        raise NotImplementedError()

    @abc.abstractmethod
    def get_working_dir(self) -> Optional[Path]:
        """Returns the path to the repository's working directory, or None if
        the working directory path is not known.
        """
        raise NotImplementedError()
