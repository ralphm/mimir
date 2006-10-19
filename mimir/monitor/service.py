# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

from zope.interface import implements, Interface
from twisted.application import service
from twisted.words.protocols.jabber import xmlstream

class IService(Interface):
    """
    External server-side component service interface.

    Services that provide this interface can be added to L{ServiceManager} to
    implement (part of) the functionality of the server-side component.
    """

    def connectionMade(xs):
        """
        Parent service has established a connection over the underlying
        transport.

        At this point, no traffic has been exchanged over the XML stream. This
        method can be used to change properties of the XML Stream (in L{xs}),
        the service manager or it's authenticator prior to stream
        initialization (including authentication).

        @param xs: XML Stream that represents the established connection.
        @type xs: L{xmlstream.XmlStream}
        """

    def connectionAuthenticated(xs):
        """
        Parent service has established a connection.

        At this point, authentication was succesful, and XML stanzas
        can be exchanged over the XML stream L{xs}. This method can be used
        to setup observers for incoming stanzas.

        @param xs: XML Stream that represents the established connection.
        @type xs: L{xmlstream.XmlStream}
        """

    def connectionLost():
        """
        Parent service has lost the connection of the underlying transport.

        Subsequent use of C{self.parent.send} will result in data being
        queued until a new connection has been established.
        """


class Service(service.Service):
    implements(IService)

    def connectionMade(self, xs):
        pass

    def connectionAuthenticated(self, xs):
        pass

    def connectionLost(self):
        pass

    def send(self, obj):
        """
        Send data over service parent's XML stream.

        @note: L{ServiceManager} maintains a queue for data sent using this
        method when there is no current established XML stream. This data is
        then sent as soon as a new stream has been established and initialized.
        Subsequently, L{componentConnected} will be called again. If this
        queueing is not desired, use C{send} on the XmlStream object (passed to
        L{componentConnected}) directly.

        @param obj: data to be sent over the XML stream. This is usually an
        object providing L{domish.IElement}, or serialized XML. See
        L{xmlstream.XmlStream} for details.
        """

        self.parent.send(obj)


class ServiceManager(service.MultiService):
    """ Business logic representing a managed XMPP connection.

    This service maintains a single XMPP connection provides facilities for
    packet routing and transmission. Business logic modules are services
    implementing L{IService} (like subclasses of L{Service}), and added as
    sub-service.

    @ivar xmlstream: currently managed XML stream
    @type xmlstream: L{xmlstream.XmlStream}
    @ivar _packetQueue: internal buffer of unsent data. See L{send} for details.
    @type _packetQueue: L{list}
    """

    def __init__(self, factory):
        service.MultiService.__init__(self)

        self.xmlstream = None
        self._packetQueue = []
        
        factory.addBootstrap(xmlstream.STREAM_CONNECTED_EVENT, self._connected)
        factory.addBootstrap(xmlstream.STREAM_AUTHD_EVENT, self._authd)
        factory.addBootstrap(xmlstream.STREAM_END_EVENT, self._disconnected)
        self.factory = factory

    def stopService(self):
        service.MultiService.stopService(self)
        self.factory.stopTrying()

    def _connected(self, xs):
        self.xmlstream = xs
        for c in self:
            if IService.providedBy(c):
                c.connectionMade(xs)

    def _authd(self, xs):
        # Flush all pending packets
        for p in self._packetQueue:
            self.xmlstream.send(p)
        self._packetQueue = []

        # Notify all child services which implement
        # the IService interface
        for c in self:
            if IService.providedBy(c):
                c.connectionAuthenticated(xs)

    def _disconnected(self, _):
        self.xmlstream = None

        # Notify all child services which implement
        # the IService interface
        for c in self:
            if IService.providedBy(c):
                c.connectionLost()

    def send(self, obj):
        """
        Send data over the XML stream.

        When there is no established XML stream, the data is queued and sent
        out when a new XML stream has been established and initialized.

        @param obj: data to be sent over the XML stream. This is usually an
        object providing L{domish.IElement}, or serialized XML. See
        L{xmlstream.XmlStream} for details.
        """

        if self.xmlstream != None:
            self.xmlstream.send(obj)
        else:
            self._packetQueue.append(obj)
