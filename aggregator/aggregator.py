import fetcher, writer
from twisted.python import log
from twisted.internet import reactor, defer
from twisted.internet.error import ConnectionLost
from twisted.words.protocols.jabber import component, client, xmlstream
from twisted.words.protocols.jabber.error import StanzaError
from twisted.words.xish import domish

INTERVAL=1800
NS_AGGREGATOR='http://mimir.ik.nu/protocol/aggregator'
NS_XMPP_STANZAS = 'urn:ietf:params:xml:ns:xmpp-stanzas'

class AggregatorService(component.Service):
    agent = "MimirAggregator/0.2 (http://mimir.ik.nu/)"

    def startService(self):
        log.FileLogObserver.timeFormat = "%Y/%m/%d %H:%M:%S %Z"
        log.msg('Starting Aggregator')

        self.writer = writer.AtomWriter()
        
        feeds = {}

        # Read feed list
        f = file('feeds')
        feed_list = [line.split() for line in f.readlines()]
        f.close()

        # Update feed data using feed list

        self.feeds = {}
        self.schedule = {}

        for handle, url in feed_list:
            if feeds.has_key(handle):
                feed = feeds[handle]

                # track url changes, and reset cache parameters
                if url != feed['url']:
                    feed['url'] = url
                    feed['etag'] = None
                    feed['last-modified'] = None

                self.feeds[handle] = feed
            else:
                self.feeds[handle] = {'handle': handle,
                                      'url': url}

        component.Service.startService(self)

    def stopService(self):
        log.msg('Stopping Aggregator')

        for call in self.schedule.itervalues():
            try:
                call.cancel()
            except ValueError:
                pass

        # save feed file
        feed_list = ["%s %s\n" % (f['handle'], f['url'])
                     for f in self.feeds.itervalues()]
        feed_list.sort()

        f = file('feeds', 'w')
        f.writelines(feed_list)
        f.close()

        component.Service.stopService(self)

    def componentConnected(self, xmlstream):
        self.xmlstream = xmlstream
        self.send = xmlstream.send

        xmlstream.addObserver('/iq[@type="set"]', self.iqFallback, -1)
        xmlstream.addObserver('/iq[@type="get"]', self.iqFallback, -1)
        xmlstream.addObserver('/iq[@type="set"]/aggregator[@xmlns="' +
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
            
            self.schedule[feed['handle']] = reactor.callLater(delay,
                                                              self.start,
                                                              feed, headers)
            delay += 5

    def componentDisconnected(self):
        for d in self.xmlstream.iqDeferreds.itervalues():
            d.errback(ConnectionLost())

        self.xmlstream.iqDeferreds = {}

        self.xmlstream = None

    def iqFallback(self, iq):
        if iq.handled == True:
            return

        self.send(StanzaError('service-unavailable').toResponse(iq))

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
            self.schedule[handle] = reactor.callLater(0, self.start,
                                                         feed,
                                                         useCache=0)
        else:
            iq = StanzaError('bad-request').toResponse(iq)
    
        self.xmlstream.send(iq)

    def start(self, feed, headers=None, useCache=1):
        d = defer.maybeDeferred(fetcher.getFeed, feed['url'], agent=self.agent,
                                                 headers=headers,
                                                 useCache=useCache)
        d.addCallback(self.workOnFeed, feed)
        d.addCallback(self.findFreshItems, feed)
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
            print "%s: Feed's location changed permanently to %s" % \
                  (feed['handle'], result.url)
            feed['url'] = result.url
        
        if result.feed:
            print "%s: Got feed." % feed["handle"]
            if result.feed.get('title', None):
                print "%s: Title: %r " % (feed["handle"],
                                          result.feed.title)
        else:
            print "%s: Not a valid feed." % feed["handle"]

        if result.bozo:
            print "%s: Bozo flag raised: %r: %s" % (feed["handle"],
                                                    result.bozo_exception,
                                                    result.bozo_exception)

        for entry in result.entries:
            if 'id' not in entry and 'link' in entry:
                entry.id = entry.link

        return result

    def publishEntries(self, entries, feed):
        print "%s: publishing items" % feed["handle"]
        
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

        return iq.send()

    def findFreshItems(self, f, feed):
        def add(entry, kind):
            print "%s: Found %s item" % (feed["handle"], kind)
            print "%s:   id: %s" % (feed["handle"], entry.id)
            if 'title' in entry:
                print "%s:   title (%s): %r" % (feed["handle"],
                                               entry.title_detail.type,
                                               entry.title_detail.value)
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
        print "%s: updating cache" % feed["handle"]
        feed['cache'] = new_cache

    def notModified(self, failure, feed):
        failure.trap(fetcher.NotModified)
        print "%s: Not Modified" % feed["handle"]

    def reschedule(self, void, feed):
        self.schedule[feed['handle']] = reactor.callLater(INTERVAL,
                                                          self.start,
                                                          feed)

    def logNoFeed(self, failure, feed):
        failure.trap(fetcher.error.Error)
        error = failure.value
        print "%s: No feed: %s" % (feed["handle"], error)

    def munchError(self, failure, feed):
        print "%s: unhandled error:" % feed["handle"]
        print failure

class LogService(component.Service):

    def transportConnected(self, xmlstream):
        xmlstream.rawDataInFn = self.rawDataIn
        xmlstream.rawDataOutFn = self.rawDataOut

    def rawDataIn(self, buf):
        print "RECV: %r" % buf

    def rawDataOut(self, buf):
        print "SEND: %r" % buf

def makeService(config):
    sm = component.buildServiceManager(config["jid"], config["secret"],
            ("tcp:%s:%s" % (config["rhost"], config["rport"])))

    # wait for no more than 15 minutes to try to reconnect
    sm.getFactory().maxDelay = 900

    if config["verbose"]:
        LogService().setServiceParent(sm)

    AggregatorService().setServiceParent(sm)

    return sm
