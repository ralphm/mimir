# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

from twisted.internet import reactor
from twisted.names.srvconnect import SRVConnector
from twisted.words.protocols.jabber import client

from mimir.common.manager import StreamManager

class XMPPClientConnector(SRVConnector):
    def __init__(self, reactor, domain, factory):
        SRVConnector.__init__(self, reactor, 'xmpp-client', domain, factory)

    def pickServer(self):
        host, port = SRVConnector.pickServer(self)

        if not self.servers and not self.orderedServers:
            # no SRV record, fall back..
            port = 5222

        return host, port

class Client(StreamManager):

    def __init__(self, jid, password):
        self.domain = jid.host

        try:
            factory = client.XMPPClientFactory(jid, password)
        except:
            factory = client.basicClientFactory(jid, password)

        StreamManager.__init__(self, factory)

    def startService(self):
        StreamManager.startService(self)

        self._connection = self._getConnection()

    def stopService(self):
        StreamManager.stopService(self)

        self._connection.disconnect()

    def _getConnection(self):
        c = XMPPClientConnector(reactor, self.domain, self.factory)
        c.connect()
        return c
