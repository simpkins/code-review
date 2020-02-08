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

import abc


class ScmAPI(object):
    def __init__(self):
        pass


class RepositoryBase(abc.ABC):
    @abc.abstractmethod
    def getDiff(self, parent, child, paths=None):
        pass

    @abc.abstractmethod
    def expand_commit_name(self, name, aliases):
        pass

    @abc.abstractmethod
    def getCommitSha1(self, name, extra_args=None):
        pass

    @abc.abstractmethod
    def is_working_dir(self, commit):
        pass

    @abc.abstractmethod
    def getBlobContents(self, commit, path, outfile=None):
        pass
