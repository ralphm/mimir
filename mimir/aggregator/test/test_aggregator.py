# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

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

class XMPPControlTest(unittest.TestCase):
    def testOnFeed(self):
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
