# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Logging facilities
"""

from twisted.python import log
from twisted.words.protocols.jabber import component

class LogService(component.Service):

    def transportConnected(self, xs):
        xs.rawDataInFn = self.rawDataIn
        xs.rawDataOutFn = self.rawDataOut

    def rawDataIn(self, buf):
        log.msg("RECV: %r" % buf)

    def rawDataOut(self, buf):
        log.msg("SEND: %r" % buf)
