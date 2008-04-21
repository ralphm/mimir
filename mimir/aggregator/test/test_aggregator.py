# Copyright (c) 2005-2008 Ralph Meijer
# See LICENSE for details

from twisted.internet import defer
from twisted.trial import unittest
from twisted.words.protocols.jabber import xmlstream

from mimir.aggregator import aggregator

class DummyManager(object):
    def __init__(self):
        self.outlist = []

    def send(self, obj):
        self.outlist.append(obj)


class DummyAggregator(object):
    def __init__(self):
        self.feeds = {}

    def setFeed(self, handle, url):
        self.feeds[handle] = url
        return defer.succeed({'handle': handle, 'url': url})


class XMPPControlTest(unittest.TestCase):
    def test_onFeed(self):
        """
        Test adding a feed through XMPP.
        """
        xc = aggregator.XMPPControl(DummyAggregator())
        xc.parent = DummyManager()

        iq = xmlstream.IQ(None)
        iq['to'] = 'user1@example.org'
        iq['from'] = 'user2@example.org'
        iq.addElement(('http://mimir.ik.nu/protocol/aggregator', 'aggregator'))
        feed = iq.aggregator.addElement('feed') 
        feed.addElement('handle', content='test')
        feed.addElement('url', content='http://www.example.org/')
        xc.onFeed(iq)
        self.assertEquals(xc.parent.outlist[0]['type'], 'result')
        self.assertEquals(xc.service.feeds['test'], 'http://www.example.org/')


class MemoryFeedStorage(object):
    def __init__(self):
        self.feeds = {}
        self.feedList = {}

    def getFeedList(self):
        return defer.succeed(self.feedList)

    def setFeedURL(self, handle, url):
        feed = {'handle': handle, 'href': url}
        self.feedList[handle] = feed
        return defer.succeed(feed)

    def getFeed(self, handle):
        return defer.succeed(self.feeds[handle])

    def storeFeed(self, feed):
        self.feeds[feed['handle']] = feed
        return defer.succeed(None)

class AggregatorTest(unittest.TestCase):

    def test_setFeed(self):
        """
        Test setting a feed to be aggregated.

        The feed should have been added to storage, and aggregation
        scheduled.
        """

        feed = {'handle': 'test', 'href': 'http://example.org/feed/atom'}

        rescheduled = []

        def reschedule(delay, handle, useCache):
            rescheduled.append((delay, handle, useCache))

        def cb2(feedList):
            self.assertIn('test', feedList)
            self.assertEquals(feed, feedList['test'])

        def cb(result):
            self.assertEquals([(0, 'test', 0)], rescheduled)
            self.assertEquals(feed, result)
            d = storage.getFeedList()
            d.addCallback(cb2)
            return d

        storage = MemoryFeedStorage()
        agg = aggregator.AggregatorService(storage)
        agg.reschedule = reschedule
        agg.startService()

        d = agg.setFeed('test', 'http://example.org/feed/atom')
        d.addCallback(cb)
        return d

    def test_setFeedInvalidHandle(self):
        """
        Test setting a feed to be aggregated, with an invalid handle.

        The feed should not have been added to storage, and aggregation
        not scheduled.
        """

        rescheduled = []

        def reschedule(delay, handle, useCache):
            rescheduled.append((delay, handle, useCache))

        def cb(result):
            self.assertEquals([], rescheduled)

        storage = MemoryFeedStorage()
        agg = aggregator.AggregatorService(storage)
        agg.reschedule = reschedule
        agg.startService()

        d = agg.setFeed('!test', 'http://example.org/feed/atom')
        self.assertFailure(d, aggregator.InvalidHandleError)
        d.addCallback(cb)
        return d
