#!/usr/local/bin/python2.6 -tt
#
# Copyright 2004-present Facebook.  All rights reserved.
#

class ArcanistError(Exception):
    pass


class ConduitClientError(ArcanistError):
    def __init__(self, code, info):
        ArcanistError.__init__(self, '%s: %s' % (code, info))
        self.code = code
        self.info = info


class NoSuchRevisionError(ConduitClientError):
    def __init__(self, rev):
        ConduitClientError.__init__(self, u'ERR_BAD_REVISION',
                                    'no such revision %s' % (rev,))
        self.rev = rev

    def __str__(self):
        return 'no such revision %s' % (self.rev,)


class PatchFailedError(Exception):
    pass
