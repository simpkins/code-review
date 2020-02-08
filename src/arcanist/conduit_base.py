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

import hashlib
import json
import socket
import sys
import time
import urllib
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

from .err import ConduitClientError


class ConduitClient(object):
    """
    A python client for making function calls to a Phabricator conduit.
    """
    RESPONSE_SHIELD = 'for(;;);'

    def __init__(self, uri, timeout=15):
        self.uri = uri
        self.session_key = None
        self.connection_id = None

        parsed_url = urlparse(self.uri)
        self.scheme = parsed_url.scheme
        self.path = parsed_url.path.rstrip('/')
        self.timeout = timeout

        parts = parsed_url.netloc.rsplit(':', 1)
        if len(parts) == 2:
            self.host = parts[0]
            try:
                self.port = int(parts[1])
                if self.port < 0 or self.port > 0xffff:
                    raise ValueError
            except ValueError:
                raise ValueError('invalid port number in conduit URI "%s"' %
                                 (uri,))
        else:
            self.host = parsed_url.netloc
            self.port = None

        if self.scheme == 'https':
            # TODO: httplib.HTTPSConnection doesn't validate the server's
            # certificate.  (Starting in python 3.2 cert validation is
            # built-in.)
            self.connection_class = HTTPSConnection
            if self.port is None:
                self.port = 443
        elif self.scheme == 'http':
            # TODO: should we just refuse to ever use plain HTTP?
            self.connection_class = HTTPConnection
            self.port = 80
        else:
            raise Exception('unsupported conduit scheme "%s"' % (self.scheme,))

    def connect(self, user, key, client=None, description=None):
        if client is None:
            client = 'pyarc'
        if description is None:
            description = socket.gethostname() + ':' + ' '.join(sys.argv)

        auth_token = '%d' % (time.time())
        auth_signature = hashlib.sha1(auth_token + key).hexdigest()

        response = self.call_method('conduit.connect',
                                    client=client,
                                    clientVersion=2,
                                    clientDescription=description,
                                    user=user,
                                    authToken=auth_token,
                                    authSignature=auth_signature)

        self.session_key = response['sessionKey']
        self.connection_id = response['connectionID']
        return response

    def call_method(self, method, **kwargs):
        if self.session_key is not None:
            conduit_params = {
                'sessionKey': self.session_key,
                'connectionID': self.connection_id,
            }
            kwargs.setdefault('__conduit__', conduit_params)

        params = {
            'params': json.dumps(kwargs),
            'output': 'json',
        }

        body = urllib.urlencode(params)

        conn = self.connection_class(self.host, self.port, strict=True,
                                     timeout=self.timeout)
        url = self.path + '/' + method
        conn.request('POST', url, body)
        response = conn.getresponse()
        response_data = response.read()

        if response.status == 302:
            # This can happen in some cases if the phabricator hosts are
            # misconfigured and attempt to redirect to a login page.
            # Include the redirect URL in the exception message to help debug
            # the issue.
            raise Exception('%s returned 302 redirect to %s in response '
                            'to conduit method call %s: %s' %
                            (self.uri, response.getheader('Location'), method,
                             response.reason))
        elif response.status != 200:
            raise Exception('%s returned HTTP error response %s in response '
                            'to conduit method call %s: %s' %
                            (self.uri, response.status, method,
                             response.reason))

        return self.parse_response(response_data)

    def parse_response(self, data):
        if data.startswith(self.RESPONSE_SHIELD):
            data = data[len(self.RESPONSE_SHIELD):]

        response = json.loads(data)

        error_code = response.get('error_code')
        if error_code:
            raise ConduitClientError(error_code, response['error_info'])

        return response['result']
