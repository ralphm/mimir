# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Feed Aggregator.

Provides a service that connects to a Jabber server as a server-side component
and continuously aggregates a collection of Atom and RSS feeds, parses them and
republishes them via Jabber publish-subscribe.
"""

from zope.interface import Interface, implements

from twisted.application import service
from twisted.internet import reactor, defer
from twisted.python import components, log
from twisted.words.protocols.jabber.error import StanzaError
from twisted.web import error

from mimir.aggregator import fetcher, writer
from mimir.common import extension, pubsub

__version__ = "0.3.0"

INTERVAL = 1800
NS_AGGREGATOR = 'http://mimir.ik.nu/protocol/aggregator'

class IFeedHandler(Interface):
    """
    Handle aggregated feeds.
    """

    def entriesDiscovered(self, handle, entries):
        """
        Called when new or updated entries have been discovered.

        @param handle: handle for the feed the entries belong to.
        @type handle: C{unicode}
        @param entries: dictionary with entry details conforming to the
                        output of the Universal Feed Parser.
        @type entries: C{dict}
        @rtype: L{defer.Deferred}
        """

class IAggregatorService(Interface):

    def setFeed(handle, url):
        """
        Associate a feed URL to a handle.

        If the handle is new, the feed is added to the aggregation schedule.

        @param handle: feed handle.
        @type handle: L{unicode}
        @param url: feed URL.
        @type url: L{str}
        """
    
class AggregatorService(service.Service):
    """
    Feed aggregator service.

    @ivar feedListFile: file that holds the list of feeds
    @type feedListFile: L{str}
    @ivar handler: handler of new and changed feed items.
    @type handler: object implementing L{IFeedHandler}
    """

    implements(IAggregatorService)

    agent = "MimirAggregator/%s (http://mimir.ik.nu/)" % __version__

    def __init__(self, feedListFile):
        self.feedListFile = feedListFile
        self.handler = None

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

        log.msg('Starting Aggregator')
        service.Service.startService(self)

        self.readFeeds()

        self.schedule = {}
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
                                                            self.aggregate,
                                                            feed, headers)
            delay += 5

    def stopService(self):
        log.msg('Stopping Aggregator')
        service.Service.stopService(self)

        calls = self.schedule.values()
        self.schedule = {}
        for call in calls:
            call.cancel()

        self.writeFeeds()


    def setFeed(self, handle, url):
        try:
            self.schedule[handle].cancel()
        except KeyError:
            pass

        feed =  {'handle': handle,
                 'url': url}
        self.feeds[handle] = feed
        self.writeFeeds()
        self.schedule[handle] = self._callLater(0, self.aggregate,
                                                   feed,
                                                   useCache=0)

    def aggregate(self, feed, headers=None, useCache=1):
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
            d = self.handler.entriesDiscovered(feed["handle"], new_entries)
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
                                                        self.aggregate,
                                                        feed)

    def logNoFeed(self, failure, feed):
        failure.trap(error.Error)
        log.msg("%s: No feed: %s" % feed["handle"])
        log.err(failure)

    def munchError(self, failure, feed):
        log.msg("%s: unhandled error:" % feed["handle"])
        log.err(failure)

class XMPPControl(extension.XMPPHandler):
    def __init__(self, service):
        self.service = service

    def connectionInitialized(self):
        xpath = '/iq[@type="set"]/aggregator[@xmlns="%s"]/feed' % NS_AGGREGATOR
        self.xmlstream.addObserver(xpath, self.onFeed, 0)

    def onFeed(self, iq):
        handle = str(iq.aggregator.feed.handle or '')
        url = str(iq.aggregator.feed.url or '')

        iq.handled = True

        if handle and url:
            try:
                self.service.setFeed(handle, url)
            except Exception, e:
                print e
                iq = StanzaError('internal-error').toResponse(iq)
            else:
                iq.swapAttributeValues('to', 'from')
                iq["type"] = 'result'
                iq.children = []
        else:
            iq = StanzaError('bad-request').toResponse(iq)
    
        self.send(iq)

components.registerAdapter(XMPPControl, IAggregatorService,
                                        extension.IXMPPHandler)

class AtomPublisher(object):
    
    implements(IFeedHandler)

    def __init__(self, protocol):
        self.protocol = protocol
        self.writer = writer.AtomWriter()

    def entriesDiscovered(self, handle, entries):
        log.msg("%s: publishing items" % handle)
       
        node = 'mimir/news/%s' % handle

        items = [pubsub.Item(entry.id, self.writer.generate(entry))
                 for entry in entries]

        return self.protocol.publish(node, items)

components.registerAdapter(AtomPublisher, pubsub.IPubSubClient,
                                          IFeedHandler)
