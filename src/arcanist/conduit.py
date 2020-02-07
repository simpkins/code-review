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

from .conduit_base import ConduitClient
from .arcrc import load_arcrc
from .working_copy import WorkingCopy


class ArcanistConduitClient(ConduitClient):
    """
    A subclass of ConduitClient that determines the Phabricator URI from the
    local .arcconfig file, and the username and certificate from the user's
    ~/.arcrc file.
    """
    def __init__(self, working_copy, user_config=None):
        if user_config is None:
            user_config = load_arcrc()

        # Allow the working_copy argument to be a WorkingCopy object
        # or a path name.
        if isinstance(working_copy, basestring):
            working_copy = WorkingCopy(working_copy)

        config = working_copy.config
        uri = config.get('conduit_uri')
        if uri is None:
            phab_uri = config.get('phabricator.uri')
            if phab_uri is None:
                msg = ('{} does not contain a conduit_uri or '
                       'phabricator.uri setting').format(config.path)
                raise KeyError(msg)
            if phab_uri.endswith('/'):
                uri = phab_uri + 'api/'
            else:
                uri = phab_uri + '/api/'

        self.host_config = user_config.hosts[uri]
        ConduitClient.__init__(self, uri)

    def connect(self):
        response = ConduitClient.connect(self, self.host_config['user'],
                                         self.host_config['cert'])
        self.user_phid = response['userPHID']
        return response
