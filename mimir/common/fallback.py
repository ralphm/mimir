# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Unhandled messages fallback services
"""

from twisted.words.protocols.jabber import component, error

class FallbackService(component.Service):
    """
    Service that catches unhandled iq requests.

    Unhandled iq requests are replied to with a service-unavailable
    stanza error.
    """

    def componentConnected(self, xs):
        xs.addObserver('/iq[@type="set"]', self.iqFallback, -1)
        xs.addObserver('/iq[@type="get"]', self.iqFallback, -1)
        
    def iqFallback(self, iq):
        if iq.handled == True:
            return

        self.send(error.StanzaError('service-unavailable').toResponse(iq))
