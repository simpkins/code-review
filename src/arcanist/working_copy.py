#!/usr/local/bin/python -tt
#
# Copyright 2011 Facebook, Inc.
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
from __future__ import absolute_import

import os

from .config import ArcConfig, NoConfigError

CEILING_DIRS = ['/', '/home']


class NoArcConfigError(Exception):
    def __init__(self, dir):
        msg = 'no .arcconfig file found in any parent of "%s"' % (dir,)
        Exception.__init__(self, msg)
        self.dir = dir


class WorkingCopy(object):
    def __init__(self, path):
        self.root, self.config = self._load_config(path)

    def _load_config(self, path):
        # Don't walk up past any of the directories listed in ARC_CEILING_DIRS
        # This can be used to prevent expensive checks in automount-controlled
        # directories.
        ceiling_dirs = os.environ.get('ARC_CEILING_DIRS', CEILING_DIRS)

        realpath = os.path.realpath(path)
        curdir = realpath
        while True:
            if curdir in ceiling_dirs:
                raise NoArcConfigError(realpath)

            arcconfig_path = os.path.join(curdir, '.arcconfig')
            try:
                config = ArcConfig(arcconfig_path)
            except NoConfigError:
                # Move up to the next directory
                next = os.path.dirname(curdir)
                if next == curdir:
                    raise NoArcConfigError(realpath)
                curdir = next
                continue

            return (curdir, config)
