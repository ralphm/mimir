# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

from twisted.trial import unittest

from twisted.test.proto_helpers import StringTransport
from twisted.internet import task
from twisted.words.protocols.jabber import xmlstream
from aggregator import aggregator

class TestableAggregatorService(aggregator.AggregatorService):

    def __init__(self, clock):
        aggregator.AggregatorService.__init__(self)
        self._callLater = clock.callLater
        xs = xmlstream.XmlStream(xmlstream.Authenticator())
        xs.transport = StringTransport()
        xs.thisHost = 'example.com'
        xs.connectionMade()
        self.xmlstream = xs

class AggregatorServiceTest(unittest.TestCase):

    def testPublishTimingOut(self):
        timings = [1, aggregator.TIMEOUT]
        clock = task.Clock()
        a = TestableAggregatorService(clock)

        d = a.publishEntries([], {'handle': 'test'})
        self.assertFailure(d, aggregator.TimeoutError)

        clock.pump(timings)
        self.failIf(clock.calls)
        return d

    def testPublishNotTimingOut(self):
        timings = [1, 1]
        clock = task.Clock()
        a = TestableAggregatorService(clock)

        d = a.publishEntries([], {'handle': 'test'})
        id = a.xmlstream.iqDeferreds.keys()[0]

        clock.callLater(1, a.xmlstream.dataReceived,
                           "<stream><iq type='result' id='%s'/>" % id)
        clock.pump(timings)
        self.failIf(clock.calls)
        return d

