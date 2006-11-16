# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

from twisted.test import proto_helpers
from twisted.trial import unittest
from twisted.words.protocols.jabber import xmlstream

from mimir.common import manager

class DummyFactory(object):
    def __init__(self):
        self.callbacks = {}

    def addBootstrap(self, event, callback):
        self.callbacks[event] = callback

class DummyXMPPHandler(object):
    def __init__(self):
        self.doneMade = 0
        self.doneInitialized = 0
        self.doneLost = 0

    def connectionMade(self):
        self.doneMade += 1

    def connectionInitialized(self):
        self.doneInitialized += 1

    def connectionLost(self):
        self.doneLost += 1

class StreamManagerTest(unittest.TestCase):

    def setUp(self):
        factory = DummyFactory()
        self.streamManager = manager.StreamManager(factory)

    def testBasic(self):
        """
        Test correct initialization and setup of factory observers.
        """
        sm = self.streamManager
        self.assertIdentical(None, sm.xmlstream)
        self.assertEquals([], sm.handlers)
        self.assertEquals(sm._connected,
                          sm.factory.callbacks['//event/stream/connected'])
        self.assertEquals(sm._authd,
                          sm.factory.callbacks['//event/stream/authd'])
        self.assertEquals(sm._disconnected,
                          sm.factory.callbacks['//event/stream/end'])

    def test_connected(self):
        """
        Test that protocol handlers have their connectionMade method called
        when the XML stream is connected.
        """
        sm = self.streamManager
        handler = DummyXMPPHandler()
        sm.addHandler(handler)
        xs = xmlstream.XmlStream(xmlstream.Authenticator())
        sm._connected(xs)
        self.assertEquals(1, handler.doneMade)
        self.assertEquals(0, handler.doneInitialized)
        self.assertEquals(0, handler.doneLost)

    def test_authd(self):
        """
        Test that protocol handlers have their connectionInitialized method
        called when the XML stream is initialized.
        """
        sm = self.streamManager
        handler = DummyXMPPHandler()
        sm.addHandler(handler)
        xs = xmlstream.XmlStream(xmlstream.Authenticator())
        sm._authd(xs)
        self.assertEquals(0, handler.doneMade)
        self.assertEquals(1, handler.doneInitialized)
        self.assertEquals(0, handler.doneLost)

    def test_disconnected(self):
        """
        Test that protocol handlers have their connectionLost method
        called when the XML stream is disconnected.
        """
        sm = self.streamManager
        handler = DummyXMPPHandler()
        sm.addHandler(handler)
        xs = xmlstream.XmlStream(xmlstream.Authenticator())
        sm._disconnected(xs)
        self.assertEquals(0, handler.doneMade)
        self.assertEquals(0, handler.doneInitialized)
        self.assertEquals(1, handler.doneLost)

    def testAddHandler(self):
        """
        Test the addition of a protocol handler while not connected.
        """
        sm = self.streamManager
        handler = DummyXMPPHandler()
        sm.addHandler(handler)
        self.assertIn(handler, sm)
        self.assertIdentical(sm, handler.manager)

        self.assertEquals(0, handler.doneMade)
        self.assertEquals(0, handler.doneInitialized)
        self.assertEquals(0, handler.doneLost)

    def testAddHandlerInitialized(self):
        """
        Test the addition of a protocol handler after the stream
        have been initialized.
        """
        sm = self.streamManager
        xs = xmlstream.XmlStream(xmlstream.Authenticator())
        sm._connected(xs)
        sm._authd(xs)
        handler = DummyXMPPHandler()
        sm.addHandler(handler)

        self.assertEquals(0, handler.doneMade)
        self.assertEquals(1, handler.doneInitialized)
        self.assertEquals(0, handler.doneLost)

    def testRemoveHandler(self):
        """
        Test removal of protocol handler.
        """
        sm = self.streamManager
        handler = DummyXMPPHandler()
        sm.addHandler(handler)
        sm.removeHandler(handler)
        self.assertNotIn(handler, sm)
        self.assertIdentical(None, handler.manager)

    def testSendInitialized(self):
        """
        Test send when the stream has been initialized.

        The data should be sent directly over the XML stream.
        """
        factory = xmlstream.XmlStreamFactory(xmlstream.Authenticator())
        sm = manager.StreamManager(factory)
        xs = factory.buildProtocol(None)
        xs.transport = proto_helpers.StringTransport()
        xs.connectionMade()
        xs.dataReceived("<stream:stream xmlns='jabber:client' "
                        "xmlns:stream='http://etherx.jabber.org/streams' "
                        "from='example.com' id='12345'>")
        xs.dispatch(xs, "//event/stream/authd")
        sm.send("<presence/>")
        self.assertEquals("<presence/>", xs.transport.value())

    def testSendNotConnected(self):
        """
        Test send when there is no established XML stream.
        
        The data should be cached until an XML stream has been established and
        initialized.
        """
        factory = xmlstream.XmlStreamFactory(xmlstream.Authenticator())
        sm = manager.StreamManager(factory)
        handler = DummyXMPPHandler()
        sm.addHandler(handler)

        xs = factory.buildProtocol(None)
        xs.transport = proto_helpers.StringTransport()
        sm.send("<presence/>")
        self.assertEquals("", xs.transport.value())
        self.assertEquals("<presence/>", sm._packetQueue[0])

        xs.connectionMade()
        self.assertEquals("", xs.transport.value())
        self.assertEquals("<presence/>", sm._packetQueue[0])

        xs.dataReceived("<stream:stream xmlns='jabber:client' "
                        "xmlns:stream='http://etherx.jabber.org/streams' "
                        "from='example.com' id='12345'>")
        xs.dispatch(xs, "//event/stream/authd")

        self.assertEquals("<presence/>", xs.transport.value())
        self.failIf(sm._packetQueue)

    def testSendNotInitialized(self):
        """
        Test send when the stream is connected but not yet initialized.
        
        The data should be cached until the XML stream has been initialized.
        """
        factory = xmlstream.XmlStreamFactory(xmlstream.Authenticator())
        sm = manager.StreamManager(factory)
        xs = factory.buildProtocol(None)
        xs.transport = proto_helpers.StringTransport()
        xs.connectionMade()
        xs.dataReceived("<stream:stream xmlns='jabber:client' "
                        "xmlns:stream='http://etherx.jabber.org/streams' "
                        "from='example.com' id='12345'>")
        sm.send("<presence/>")
        self.assertEquals("", xs.transport.value())
        self.assertEquals("<presence/>", sm._packetQueue[0])

    def testSendDisconnected(self):
        """
        Test send after XML stream disconnection.
        
        The data should be cached until a new XML stream has been established
        and initialized.
        """
        factory = xmlstream.XmlStreamFactory(xmlstream.Authenticator())
        sm = manager.StreamManager(factory)
        handler = DummyXMPPHandler()
        sm.addHandler(handler)

        xs = factory.buildProtocol(None)
        xs.connectionMade()
        xs.transport = proto_helpers.StringTransport()
        xs.connectionLost(None)

        sm.send("<presence/>")
        self.assertEquals("", xs.transport.value())
        self.assertEquals("<presence/>", sm._packetQueue[0])
