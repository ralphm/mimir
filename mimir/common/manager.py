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
    providing L{IXMPPHandler} (like subclasses of L{XMPPHandler}),
    and added using L{addHandler}.

    @ivar xmlstream: currently managed XML stream
    @type xmlstream: L{xmlstream.XmlStream}
    @ivar handlers: list of protocol handlers
    @type handlers: L{list} of objects providing
                      L{extensions.IXMPPHandler}
    @ivar logTraffic: if true, log all traffic.
    @type logTraffic: L{bool}
    @ivar _packetQueue: internal buffer of unsent data. See L{send} for details.
    @type _packetQueue: L{list}
    """

    logTraffic = False

    def __init__(self, factory):
        self.handlers = []
        self.xmlstream = None
        self._packetQueue = []
        self._initialized = False
        
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
        self._initialized = True

        # Notify all child services which implement
        # the IService interface
        for e in self:
            e.connectionInitialized()

    def _disconnected(self, _):
        self.xmlstream = None
        self._initialized = False

        # Notify all child services which implement
        # the IService interface
        for e in self:
            e.xmlstream = None
            e.connectionLost()

    def __iter__(self):
        return iter(self.handlers)

    def addHandler(self, handler):
        """
        Add protocol handler.

        Protocol handlers are expected to provide L{extension.IXMPPHandler}.
        
        When an XML stream has already been established, the handler's
        C{connectionInitialized} will be called to get it up to speed.
        """

        self.handlers.append(handler)
        handler.manager = self

        # get protocol handler up to speed when a connection has already
        # been established
        if self.xmlstream and self._initialized:
            handler.connectionInitialized()

    def removeHandler(self, handler):
        """
        Remove protocol handler.
        """

        handler.manager = None
        self.handlers.remove(handler)

    def send(self, obj):
        """
        Send data over the XML stream.

        When there is no established XML stream, the data is queued and sent
        out when a new XML stream has been established and initialized.

        @param obj: data to be sent over the XML stream. See
                    L{xmlstream.XmlStream.send} for details. 
        """

        if self._initialized:
            self.xmlstream.send(obj)
        else:
            self._packetQueue.append(obj)
