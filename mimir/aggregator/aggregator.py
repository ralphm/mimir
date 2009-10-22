# Copyright (c) 2005-2009 Ralph Meijer
# See LICENSE for details

"""
Feed Aggregator.

Provides a service that connects to a Jabber server as a server-side component
and continuously aggregates a collection of Atom and RSS feeds, parses them and
republishes them via Jabber publish-subscribe.
"""

import re
import simplejson

from zope.interface import Interface, implements

from twisted.application import service
from twisted.internet import reactor, defer
from twisted.python import components, log
from twisted.python.filepath import FilePath
from twisted.words.protocols.jabber import xmlstream
from twisted.words.protocols.jabber.error import StanzaError
from twisted.words.xish import domish
from twisted.web import error
from twisted.web2 import http, resource, responsecode
from twisted.web2.stream import readStream

from wokkel import pubsub
from wokkel.iwokkel import IXMPPHandler
from wokkel.subprotocols import XMPPHandler

from mimir import __version__
from mimir.aggregator import fetcher, writer
from mimir.monitor.news import FeedParserEncoder

INTERVAL = 1800
NS_AGGREGATOR = 'http://mimir.ik.nu/protocol/aggregator'

RE_HANDLE = re.compile('^[-a-z0-9_]+$')

class InvalidHandleError(Exception):
    """
    Handle contains invalid characters.
    """


class IFeedHandler(Interface):
    """
    Handle aggregated feeds.
    """

    def entriesDiscovered(self, handle, feed, entries):
        """
        Called when new or updated entries have been discovered.

        @param handle: Handle for the feed the entries belong to.
        @type handle: C{unicode}
        @param feed: Output from the Universal Feed Parser.
        @type feed: L{feedparser.FeedParserDict}
        @param entries: List with entry details conforming to the
                        output of the Universal Feed Parser.
        @type entries: C{list}
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


class FileFeedStorage(object):
    def __init__(self, feedsDir):
        self.feedsDir = FilePath(feedsDir)
        self.feedListFile = self.feedsDir.child('feeds')
        self.feeds = None

    def _readFeedList(self):
        """
        Initialize list of feeds
        """

        fh = self.feedListFile.open()
        try:
            feedList = [line.split() for line in fh.readlines()]
        finally:
            fh.close()

        self.feeds = {}
        for handle, url in feedList:
            self.feeds[handle] = {'handle': handle,
                                  'href': url}

    def _writeFeedList(self):
        """
        Write out list of feeds
        """

        feedList = ["%s %s\n" % (f['handle'], f['href'])
                     for f in self.feeds.itervalues()]
        feedList.sort()

        fh = self.feedListFile.open('w')
        try:
            fh.writelines(feedList)
        finally:
            fh.close()

    def getFeedList(self):
        """
        Get the list of feeds.
        """
        if self.feeds is None:
            try:
                self._readFeedList()
            except:
                return defer.fail()

        return defer.succeed(self.feeds)

    def setFeedURL(self, handle, url):
        """
        Add or update the feed.
        """
        feed = {'handle': handle,
                 'href': url}

        self.feeds[handle] = feed

        try:
            self.storeFeed(feed)
            self._writeFeedList()
        except:
            return defer.fail()

        return defer.succeed(feed)

    def getFeed(self, handle):
        """
        Retrieve the feed as it was last aggregated.
        """

        try:
            feedFile = self.feedsDir.child("%s.feed.json" % handle)

            feed = self.feeds[handle]
            if feedFile.exists():
                fh = feedFile.open()
                try:
                    try:
                        feed = simplejson.load(fh)
                    except ValueError:
                        pass
                finally:
                    fh.close()
        except:
            return defer.fail()

        return defer.succeed(feed)

    def storeFeed(self, feed):
        """
        Write out a feed as a JSON file.
        """

        try:
            feedFile = self.feedsDir.child("%s.feed.json" % feed['handle'])
            if feedFile.exists():
                feedFile.moveTo(FilePath(feedFile.path + '.1'))
            fh = feedFile.open("w")
            try:
                simplejson.dump(feed, fh, indent=4, cls=FeedParserEncoder)
            finally:
                fh.close()
        except:
            return defer.fail()
        else:
            return defer.succeed(feed)



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

    def __init__(self, storage):
        self.handler = None
        self.storage = storage

    def _callLater(self, *args, **kwargs):
        """
        Make callLater calls indirect for testing purposes.
        """

        return reactor.callLater(*args, **kwargs)

    def startService(self):
        """
        Read feeds from file and initialize service.
        """

        log.msg('Starting Aggregator')
        service.Service.startService(self)

        self.schedule = {}

        def scheduleFeeds(feeds):
            delay = 5
            for handle in feeds:
                self.reschedule(delay, handle)
                delay += 5

        d = self.storage.getFeedList()
        d.addCallback(scheduleFeeds)

    def stopService(self):
        log.msg('Stopping Aggregator')
        service.Service.stopService(self)

        calls = self.schedule.values()
        self.schedule = {}
        for call in calls:
            call.cancel()

    def setFeed(self, handle, url):
        if not RE_HANDLE.match(handle):
            return defer.fail(InvalidHandleError())

        try:
            self.schedule[handle].cancel()
        except KeyError:
            pass

        def scheduleFeed(result):
            if self.running:
                self.reschedule(0, handle, useCache=0)
            return result

        d = self.storage.setFeedURL(handle, url)
        d.addCallback(scheduleFeed)
        return d

    def aggregate(self, handle, useCache=1):
        def setInterval(feed, cachedFeed):
            feed['interval'] = cachedFeed['interval']
            return feed

        def aggregateFeed(cachedFeed):
            headers = {}

            if 'interval' not in cachedFeed:
                cachedFeed['interval'] = INTERVAL

            if useCache:
                etag = cachedFeed.get('etag', None)
                updated = cachedFeed.get('updated', None)
                if etag:
                    headers['If-None-Match'] = str(etag)
                if updated:
                    short_weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri',
                                      'Sat', 'Sun']
                    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                    headers['If-Modified-Since'] = \
                        '%s, %02d %s %04d %02d:%02d:%02d GMT' % (
                                short_weekdays[updated[6]],
                                updated[2],
                                months[updated[1] - 1],
                                updated[0],
                                updated[3], updated[4], updated[5])

            d = defer.maybeDeferred(fetcher.getFeed, str(cachedFeed['href']),
                                                     agent=self.agent,
                                                     headers=headers,
                                                     useCache=useCache)
            d.addCallback(self.workOnFeed, handle)
            d.addCallback(self.findFreshEntries, handle, cachedFeed)
            d.addCallback(setInterval, cachedFeed)
            d.addCallback(self.updateCache)
            d.addErrback(self.notModified, handle)
            d.addErrback(self.logNoFeed, handle)
            d.addErrback(self.munchError, handle)
            d.addBoth(lambda _: self.reschedule(cachedFeed['interval'], handle))
            return d

        d = self.storage.getFeed(handle)
        d.addCallback(aggregateFeed)
        return d

    def workOnFeed(self, result, handle):
        result['handle'] = handle

        if result.status == '301':
            log.msg("%s: Feed's location changed permanently to %s" %
                    (handle, result.href))
            self.storage.setFeedURL(handle, result.href)

        if result.feed:
            log.msg("%s: Got feed." % handle)
            if 'title' in result.feed:
                log.msg("%s: Title: %r " % (handle,
                                            result.feed.title))
        else:
            log.msg("%s: Not a valid feed." % handle)

        if result.bozo:
            log.err(result.bozo_exception, "%s: Bozo flag raised" % handle)

        for entry in result.entries:
            if 'id' not in entry and 'link' in entry:
                entry.id = entry.link

        return result

    def findFreshEntries(self, result, handle, cachedFeed):
        def add(entry, kind):
            log.msg("%s: Found %s entry" % (handle, kind))
            log.msg("%s:   id: %s" % (handle, entry.id))
            if 'title' in entry:
                log.msg("%s:   title (%s): %r" % (handle,
                                                  entry.title_detail.type,
                                                  entry.title_detail.value))
            discoveredEntries.append(entry)

        cacheIndexes = cachedFeed.get('indexes', {})

        newCacheIndexes = {}
        discoveredEntries = []

        index = len(result.entries)
        for entry in reversed(result.entries):
            index -= 1

            if 'id' not in entry:
                continue

            if entry.id not in cacheIndexes:
                add(entry, 'new')
            else:
                jsonEntry = simplejson.dumps(entry, cls=FeedParserEncoder)
                newEntry = simplejson.loads(jsonEntry)
                if cachedFeed['entries'][cacheIndexes[entry.id]] != newEntry:
                    add(entry, 'updated')

            newCacheIndexes[entry.id] = index

        result['indexes'] = newCacheIndexes

        if discoveredEntries:
            d = self.handler.entriesDiscovered(handle, result,
                                               discoveredEntries)
        else:
            d = defer.succeed(None)

        d.addCallback(lambda _: result)
        return d

    def updateCache(self, result):
        log.msg("%s: updating cache" % result["handle"])
        return self.storage.storeFeed(result)

    def notModified(self, failure, handle):
        failure.trap(fetcher.NotModified)
        log.msg("%s: Not Modified" % handle)

    def reschedule(self, delay, handle, useCache=1):
        def cb():
            del self.schedule[handle]
            self.aggregate(handle, useCache=useCache)

        self.schedule[handle] = self._callLater(delay, cb)

    def logNoFeed(self, failure, handle):
        failure.trap(error.Error)
        log.err(failure, "%s: No feed" % handle)

    def munchError(self, failure, handle):
        log.err(failure, "%s: Unhandled Error" % handle)


class XMPPControl(XMPPHandler):

    def __init__(self, service):
        self.service = service

    def connectionInitialized(self):
        xpath = '/iq[@type="set"]/aggregator[@xmlns="%s"]/feed' % NS_AGGREGATOR
        self.xmlstream.addObserver(xpath, self.onFeed, 0)

    def onFeed(self, iq):
        handle = str(iq.aggregator.feed.handle or '')
        url = str(iq.aggregator.feed.url or '')

        iq.handled = True

        def success(_):
            return xmlstream.toResponse(iq, 'result')

        def trapInvalidHandle(failure):
            failure.trap(InvalidHandleError)
            raise StanzaError('bad-request', text='Invalid handle')

        def error(failure):
            if failure.check(StanzaError):
                exc = failure.value
            else:
                log.err(failure)
                exc = StanzaError('internal-error')
            return exc.toResponse(iq)

        if handle and url:
            d = self.service.setFeed(handle, url)
            d.addCallback(success)
            d.addErrback(trapInvalidHandle)
        else:
            d = defer.fail(StanzaError('bad-request'))

        d.addErrback(error)
        d.addCallback(self.send)

components.registerAdapter(XMPPControl, IAggregatorService,
                                        IXMPPHandler)


class AddFeedResource(resource.Resource):
    """
    Resource to add a new feed to be aggregated.
    """

    def __init__(self, service):
        self.service = service

    http_GET = None

    def http_POST(self, request):
        def gotRequest(result):
            url = result['url']
            handle = result['handle']
            d = self.service.setFeed(handle, url)
            d.addCallback(lambda _: self.service.handler.checkNode(handle))
            return d

        def createResponse(result):
            response = {'uri': 'xmpp:%s?;node=%s' % (
                self.service.handler.service.full(),
                result)}
            return http.Response(responsecode.OK, stream=simplejson.dumps(response))

        def trapInvalidHandle(failure):
            failure.trap(InvalidHandleError)
            return http.StatusResponse(responsecode.BAD_REQUEST,
                                       """Invalid handle""")

        data = []
        d = readStream(request.stream, data.append)
        d.addCallback(lambda _: ''.join(data))
        d.addCallback(simplejson.loads)
        d.addCallback(gotRequest)
        d.addCallback(createResponse)
        d.addErrback(trapInvalidHandle)
        return d



class AtomPublisher(object):

    implements(IFeedHandler)

    def __init__(self, protocol):
        self.protocol = protocol
        self.service = None
        self.writer = writer.ReconstituteWriter()


    def _getNode(self, handle):
        return 'mimir/news/%s' % handle


    def entriesDiscovered(self, handle, feed, entries):
        log.msg("%s: publishing items" % handle)

        node = self._getNode(handle)

        items = []
        for entry in entries:
            try:
                entryDoc = self.writer.generate(feed, entry)
            except domish.ParserError:
                log.err(None, '%s: Error processing entry: %r' % (handle,
                                                                  entry.title))
            else:
                items.append(pubsub.Item(entry.id, entryDoc))

        if items:
            return self.protocol.publish(self.service, node, items)
        else:
            return defer.succeed(None)

    def checkNode(self, handle):
        def trapConflict(failure, node):
            failure.trap(StanzaError)
            exc = failure.value
            if exc.condition != 'conflict':
                return failure
            else:
                return node

        node = self._getNode(handle)
        d = self.protocol.createNode(self.service, node)
        d.addErrback(trapConflict, node)
        return d

components.registerAdapter(AtomPublisher, pubsub.IPubSubClient,
                                          IFeedHandler)
