# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

from twisted.application import service
from twisted.python import log
from twisted.words.protocols.jabber import xmlstream

class StreamManager(service.Service):
    """
    Business logic representing a managed XMPP connection.

    This service maintains a single XMPP connection and provides facilities for
    packet routing and transmission. Business logic modules are objects
    providing L{IExtensionProtocol} (like subclasses of L{ExtensionProtocol}),
    and added using L{addExtension}.

    @ivar xmlstream: currently managed XML stream
    @type xmlstream: L{xmlstream.XmlStream}
    @ivar extensions: list of extension protocol handlers
    @type extensions: L{list} of objects providing
                      L{extensions.IExtensionProtocol}
    @ivar logTraffic: if true, log all traffic.
    @type logTraffic: L{bool}
    @ivar _packetQueue: internal buffer of unsent data. See L{send} for details.
    @type _packetQueue: L{list}
    """

    logTraffic = False

    def __init__(self, factory):
        self.extensions = []
        self.xmlstream = None
        self._packetQueue = []
        
        factory.addBootstrap(xmlstream.STREAM_CONNECTED_EVENT, self._connected)
        factory.addBootstrap(xmlstream.STREAM_AUTHD_EVENT, self._authd)
        factory.addBootstrap(xmlstream.STREAM_END_EVENT, self._disconnected)
        self.factory = factory

    def stopService(self):
        service.Service.stopService(self)

        # If the factory is a ReconnectingClientFactory, try stopping it from
        # establishing a new connection.
        try:
            self.factory.stopTrying()
        except AttributeError:
            pass
        
    def _connected(self, xs):
        def logDataIn(buf):
            log.msg("RECV: %r" % buf)

        def logDataOut(buf):
            log.msg("SEND: %r" % buf)

        if self.logTraffic:
            xs.rawDataInFn = logDataIn
            xs.rawDataOutFn = logDataOut

        self.xmlstream = xs
        for e in self:
            e.xmlstream = xs
            e.connectionMade()

    def _authd(self, xs):
        # Flush all pending packets
        for p in self._packetQueue:
            xs.send(p)
        self._packetQueue = []

        # Notify all child services which implement
        # the IService interface
        for e in self:
            e.connectionInitialized()

    def _disconnected(self, _):
        self.xmlstream = None

        # Notify all child services which implement
        # the IService interface
        for e in self:
            e.xmlstream = None
            e.connectionLost()

    def __iter__(self):
        return iter(self.extensions)

    def addExtension(self, extension):
        """
        Add extension handler.

        Extension handlers are expected to provide
        L{extension.IExtensionProtocol}.
        
        When an XML stream has already been established, the handler's
        C{connectionInitialized} will be called to get it up to speed.
        """

        self.extensions.append(extension)
        extension.manager = self

        # get extension handler up to speed when a connection has already
        # been established
        if self.xmlstream:
            extension.connectionInitialized()

    def removeExtension(self, extension):
        """
        Remove extension handler.
        """

        self.extensions.remove(extension)

    def send(self, obj):
        """
        Send data over the XML stream.

        When there is no established XML stream, the data is queued and sent
        out when a new XML stream has been established and initialized.

        @param obj: data to be sent over the XML stream. See
                    L{xmlstream.XmlStream.send} for details. 
        """

        if self.xmlstream != None:
            self.xmlstream.send(obj)
        else:
            self._packetQueue.append(obj)
