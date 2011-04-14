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
import pwd

from .config import ArcConfig


def get_homedir():
    try:
        return os.environ['HOME']
    except KeyError:
        pass

    pwent = pwd.getpwuid(os.getuid())
    return pwent.pw_dir


def load_arcrc():
    arcrc_path = os.path.join(get_homedir(), '.arcrc')
    return ArcConfig(arcrc_path, default={})
