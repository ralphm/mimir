from twisted.application import internet
from twisted.names.srvconnect import SRVConnector
from twisted.words.protocols.jabber import client
import service

class XMPPClientConnector(SRVConnector):
    def __init__(self, reactor, domain, factory):
        SRVConnector.__init__(self, reactor, 'xmpp-client', domain, factory)

    def pickServer(self):
        host, port = SRVConnector.pickServer(self)

        if not self.servers and not self.orderedServers:
            # no SRV record, fall back..
            port = 5222

        return host, port

class XMPPTCPClient(internet.TCPClient):
    def _getConnection(self):
        from twisted.internet import reactor
        c = XMPPClientConnector(reactor, *self.args, **self.kwargs)
        c.connect()
        return c

def buildClientServiceManager(jid, password):
    factory = client.XMPPClientFactory(jid, password)
    svc = service.ServiceManager(factory)
    client_svc = XMPPTCPClient(jid.host, factory)
    client_svc.setServiceParent(svc)
    return svc
