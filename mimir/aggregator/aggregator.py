# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Feed Aggregator.

Provides a service that connects to a Jabber server as a server-side component
and continuously aggregates a collection of Atom and RSS feeds, parses them and
republishes them via Jabber publish-subscribe.
"""

from twisted.internet import reactor, defer
from twisted.python import log
from twisted.words.protocols.jabber import component, xmlstream
from twisted.words.protocols.jabber.error import StanzaError

from mimir.aggregator import fetcher, writer

__version__ = "0.3.0"

INTERVAL = 1800
TIMEOUT = 300
NS_AGGREGATOR = 'http://mimir.ik.nu/protocol/aggregator'
NS_XMPP_STANZAS = 'urn:ietf:params:xml:ns:xmpp-stanzas'

class TimeoutError(Exception):
    """
    No response has been received to our request within L{TIMEOUT} seconds.
    """

class AggregatorService(component.Service):
    """
    Feed aggregator service.

    @ivar feedListFile: file that holds the list of feeds
    @type feedListFile: L{str}
    """

    agent = "MimirAggregator/%s (http://mimir.ik.nu/)" % __version__

    def __init__(self, feedListFile):
        self.feedListFile = feedListFile
        self._runningQueries = {}
        
    def _callLater(self, *args, **kwargs):
        """
        Make callLater calls indirect for testing purposes.
        """

        return reactor.callLater(*args, **kwargs)

    def readFeeds(self):
        """
        Initialize list of feeds
        """

        f = file(self.feedListFile)
        feedList = [line.split() for line in f.readlines()]
        f.close()

        self.feeds = {}
        for handle, url in feedList:
            self.feeds[handle] = {'handle': handle,
                                  'url': url}

    def writeFeeds(self):
        """
        Write out list of feeds
        """

        feedList = ["%s %s\n" % (f['handle'], f['url'])
                     for f in self.feeds.itervalues()]
        feedList.sort()

        f = file(self.feedListFile, 'w')
        f.writelines(feedList)
        f.close()

    def startService(self):
        """
        Read feeds from file and initialize service.
        """
        log.FileLogObserver.timeFormat = "%Y/%m/%d %H:%M:%S %Z"
        log.msg('Starting Aggregator')

        self.writer = writer.MimirWriter()

        self.schedule = {}
        self._runningQueries = {}

        self.readFeeds()

        component.Service.startService(self)

    def stopService(self):
        log.msg('Stopping Aggregator')

        self.writeFeeds()

        component.Service.stopService(self)

    def componentConnected(self, xs):
        self.xmlstream = xs

        xs.addObserver('/iq[@type="set"]', self.iqFallback, -1)
        xs.addObserver('/iq[@type="get"]', self.iqFallback, -1)
        xs.addObserver('/iq[@type="set"]/aggregator[@xmlns="' +
                              NS_AGGREGATOR + '"]/feed', self.onFeed, 0)
       
        delay = 0
        for feed in self.feeds.itervalues():
            headers = {}
            etag = feed.get('etag', None)
            last_modified = feed.get('last-modified', None)
            if etag:
                headers['if-none-match'] = etag
            if last_modified:
                headers['if-modified-since'] = last_modified
            
            self.schedule[feed['handle']] = self._callLater(delay,
                                                            self.start,
                                                            feed, headers)
            delay += 5

    def componentDisconnected(self):
        self.xmlstream = None

        calls = self.schedule.values()
        self.schedule = {}
        for call in calls:
            call.cancel()

    def iqFallback(self, iq):
        if iq.handled == True:
            return

        self.xmlstream.send(StanzaError('service-unavailable').toResponse(iq))

    def onFeed(self, iq):
        handle = str(iq.aggregator.feed.handle or '')
        url = str(iq.aggregator.feed.url or '')

        iq.handled = True

        if handle and url:
            iq.swapAttributeValues('to', 'from')
            iq["type"] = 'result'
            iq.children = []

            try:
                self.schedule[handle].cancel()
            except KeyError:
                pass

            feed =  {'handle': handle,
                     'url': url}
            self.feeds[handle] = feed
            self.writeFeeds()
            self.schedule[handle] = self._callLater(0, self.start,
                                                       feed,
                                                       useCache=0)
        else:
            iq = StanzaError('bad-request').toResponse(iq)
    
        self.xmlstream.send(iq)

    def start(self, feed, headers=None, useCache=1):
        del self.schedule[feed['handle']]

        d = defer.maybeDeferred(fetcher.getFeed, feed['url'], agent=self.agent,
                                                 headers=headers,
                                                 useCache=useCache)
        d.addCallback(self.workOnFeed, feed)
        d.addCallback(self.findFreshEntries, feed)
        d.addCallback(self.updateCache, feed)
        d.addErrback(self.notModified, feed)
        d.addErrback(self.logNoFeed, feed)
        d.addErrback(self.munchError, feed)
        d.addBoth(self.reschedule, feed)
        return d

    def workOnFeed(self, result, feed):
        feed['etag'] = result.headers.get('etag', None)
        feed['last-modified'] = result.headers.get('last-modified', None)

        if result.status == '301':
            log.msg("%s: Feed's location changed permanently to %s" %
                    (feed['handle'], result.url))
            feed['url'] = result.url
            self.writeFeeds()
        
        if result.feed:
            log.msg("%s: Got feed." % feed["handle"])
            if result.feed.get('title', None):
                log.msg("%s: Title: %r " % (feed["handle"],
                                            result.feed.title))
        else:
            log.msg("%s: Not a valid feed." % feed["handle"])

        if result.bozo:
            log.msg("%s: Bozo flag raised: %r: %s" % (feed["handle"],
                                                      result.bozo_exception,
                                                      result.bozo_exception))

        for entry in result.entries:
            if 'id' not in entry and 'link' in entry:
                entry.id = entry.link

        return result

    def publishEntries(self, entries, feed):
        log.msg("%s: publishing items" % feed["handle"])
        
        iq = xmlstream.IQ(self.xmlstream, 'set')
        iq['to'] = 'pubsub.ik.nu'
        iq['from'] = self.xmlstream.thisHost
        iq.addElement(('http://jabber.org/protocol/pubsub', 'pubsub'))
        iq.pubsub.addElement('publish')
        iq.pubsub.publish["node"] = 'mimir/news/%s' % feed["handle"]

        for entry in entries:
            item = iq.pubsub.publish.addElement('item')
            item["id"] = entry.id
            item.addChild(self.writer.generate(entry))

        d = iq.send()
        id = iq['id']

        def timeout():
            del self._runningQueries[id]
            d.errback(TimeoutError("IQ timed out"))

            try:
                del self.xmlstream.iqDeferreds[id]
            except KeyError:
                pass

        def cancelTimeout(result):
            try:
                self._runningQueries[id].cancel()
                del self._runningQueries[id]
            except KeyError:
                pass

            return result

        self._runningQueries[id] = self._callLater(TIMEOUT, timeout)
        d.addBoth(cancelTimeout)
        return d

    def findFreshEntries(self, f, feed):
        def add(entry, kind):
            log.msg("%s: Found %s entry" % (feed["handle"], kind))
            log.msg("%s:   id: %s" % (feed["handle"], entry.id))
            if 'title' in entry:
                log.msg("%s:   title (%s): %r" % (feed["handle"],
                                                  entry.title_detail.type,
                                                  entry.title_detail.value))
            new_entries.append(entry)

        cache = feed.get('cache', {})

        new_cache = {}
        new_entries = []
        for entry in reversed(f.entries):
            if 'id' not in entry:
                continue

            if entry.id not in cache:
                add(entry, 'new')
            elif cache[entry.id] != entry:
                add(entry, 'updated')

            new_cache[entry.id] = entry

        if new_entries:
            d = self.publishEntries(new_entries, feed)
        else:
            d = defer.succeed(None)

        d.addCallback(lambda _: new_cache)
        return d

    def updateCache(self, new_cache, feed):
        log.msg("%s: updating cache" % feed["handle"])
        feed['cache'] = new_cache

    def notModified(self, failure, feed):
        failure.trap(fetcher.NotModified)
        log.msg("%s: Not Modified" % feed["handle"])

    def reschedule(self, void, feed):
        self.schedule[feed['handle']] = self._callLater(INTERVAL,
                                                        self.start,
                                                        feed)

    def logNoFeed(self, failure, feed):
        failure.trap(fetcher.error.Error)
        error = failure.value
        log.msg("%s: No feed: %s" % (feed["handle"], error))

    def munchError(self, failure, feed):
        log.msg("%s: unhandled error:" % feed["handle"])
        log.err(failure)
