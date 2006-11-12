"""
XMPP External Component utilities
"""

from twisted.internet import reactor
from twisted.words.protocols.jabber import component
from twisted.words.xish import domish
from mimir.common.manager import StreamManager

class Component(StreamManager):
    def __init__(self, host, port, jid, password):
        self.host = host
        self.port = port

        factory = component.componentFactory(jid, password)

        StreamManager.__init__(self, factory)

    def _authd(self, xs):
        old_send = xs.send

        def send(obj):
            if domish.IElement.providedBy(obj) and \
                    not obj.getAttribute('from'):
                obj['from'] = self.xmlstream.thisHost
            old_send(obj)

        xs.send = send
        StreamManager._authd(self, xs)

    def startService(self):
        StreamManager.startService(self)

        self._connection = self._getConnection()

    def stopService(self):
        StreamManager.stopService(self)

        self._connection.disconnect()

    def _getConnection(self):
        return reactor.connectTCP(self.host, self.port, self.factory)
