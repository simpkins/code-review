#!/usr/bin/python -tt
#
# Copyright 2004-present Facebook. All Rights Reserved.
#

class ScmAPI(object):
    def __init__(self):
        pass

    def expand_commit(self, string, aliases):
        raise NotImplementedError('expand_commit() must be implemented by '
                                  'ScmAPI subclasses')
