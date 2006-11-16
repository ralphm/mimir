# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Unhandled messages fallback handler
"""

from twisted.words.protocols.jabber import error
from mimir.common import extension

class FallbackHandler(extension.XMPPHandler):
    """
    Protocol handler that catches unhandled iq requests.

    Unhandled iq requests are replied to with a service-unavailable stanza
    error.
    """

    def connectionInitialized(self):
        self.xmlstream.addObserver('/iq[@type="set"]', self.iqFallback, -1)
        self.xmlstream.addObserver('/iq[@type="get"]', self.iqFallback, -1)
        
    def iqFallback(self, iq):
        if iq.handled == True:
            return

        reply = error.StanzaError('service-unavailable')
        self.xmlstream.send(reply.toResponse(iq))
