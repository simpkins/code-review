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
from __future__ import absolute_import, division, print_function

import codecs
import errno
import json


class NoConfigError(Exception):
    def __init__(self, path):
        msg = str(path) + ': arc configuration file does not exist'
        Exception.__init__(self, msg)
        self.path = path


class NoConfigKeyError(KeyError):
    def __init__(self, path, key):
        # The key is a list of the names at each sublevel.
        # Convert it into a somewhat more human-readable string.  e.g.,
        # ['hosts', 'https://secure.phabricator.com/api/'] becomes
        # [hosts]->[https://secure.phabricator.com/api/]
        name = '[' + ']->['.join(key) + ']'
        msg = '%s does not contain a %s setting' % (path, name)

        KeyError.__init__(self, msg)
        self.path = path
        self.key = key


class ArcConfigDict(object):
    """
    A dict-like object that raises NoConfigKeyError if you try to access
    a key that doesn't exist.

    It also allows accessing the keys using member-variable syntax.

    ArcConfigDict is used to represent the top-level config, as well as any
    internal dictionaries stored in the config.
    """
    def __init__(self, path, name, values):
        self.path = path
        # self.name is the name of this entry in the config file, stored as a
        # list of the key names at each sublevel.  For the top-level config,
        # this is the empty list.  For a dictionary stored at
        # config["foo"]["bar"], this would be ["foo", "bar"]
        self.name = name
        # self.values it the contents of this config dictionary.
        self.values = values

    def __len__(self):
        return len(self.values)

    def __getitem__(self, key):
        try:
            value = self.values[key]
        except KeyError:
            raise NoConfigKeyError(self.path, self.name + [key])

        if isinstance(value, dict):
            return ArcConfigDict(self.path, self.name +  [key], value)
        return value

    def __getattr__(self, key):
        if key.startswith('__'):
            raise AttributeError(key)
        return self.__getitem__(key)

    def get(self, key, default=None):
        return self.values.get(key, default)


class ArcConfig(ArcConfigDict):
    def __init__(self, path, default=None):
        values = self._load(path, default)
        ArcConfigDict.__init__(self, path, [], values)

    def _load(self, path, default):
        try:
            f = codecs.open(path, 'r', encoding='utf-8')
        except IOError as ex:
            if ex.errno == errno.ENOENT:
                if default is None:
                    raise NoConfigError(path)
                return default
            raise

        try:
            return json.loads(f.read())
        finally:
            f.close()
