import fetcher
import xmpp_error
from twisted.python import log
from twisted.internet import reactor, defer
from twisted.persisted import sob
from twisted.xish import domish
from twisted.words.protocols.jabber import component, client

INTERVAL=1800
NS_AGGREGATOR='http://mimir.ik.nu/protocol/aggregator'
NS_XMPP_STANZAS = 'urn:ietf:params:xml:ns:xmpp-stanzas'

class AggregatorService(component.Service):
    agent = "MimirAggregator/0.2 (http://mimir.ik.nu/)"

    def startService(self):
        log.FileLogObserver.timeFormat = "%Y/%m/%d %H:%M:%S %Z"
        log.msg('Starting Aggregator')
        
        # Load feed data from persistent storage
        try:
            feeds = sob.load('feeds.tap', 'pickle')
        except IOError:
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

        # make feeds object persistent
        self.persistent = sob.Persistent(self.feeds, 'feeds')

        component.Service.startService(self)

    def stopService(self):
        log.msg('Stopping Aggregator')

        self.persistent.save()

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

    def iqFallback(self, iq):
        if iq.handled == True:
            return

        self.send(xmpp_error.error_from_iq(iq, 'service-unavailable'))

    def onFeed(self, iq):
        handle = str(iq.aggregator.feed.handle or '')
        url = str(iq.aggregator.feed.url or '')

        iq.swapAttributeValues('to', 'from')
        iq.handled = True

        if handle and url:
            iq["type"] = 'result'
            iq.children = []

            try:
                feed = self.feeds['handle']
                feed['url'] = url
                self.schedule[handle].cancel()
            except KeyError:
                feed = {'handle': handle, 'url': url}

            self.feeds[handle] = feed
            self.schedule[handle] = reactor.callLater(0, self.start, feed)
        else:
            iq['type'] = 'error'
            e = iq.addElement('error')
            e['code'] = 400
            e['type'] = 'modify'
            c = e.addElement((NS_XMPP_STANZAS, 'bad-request'), NS_XMPP_STANZAS)
    
        self.xmlstream.send(iq)

    def start(self, feed, headers=None):
        d = fetcher.getFeed(feed['url'], agent=self.agent, headers=headers)
        d.addCallback(self.workOnFeed, feed)
        d.addCallback(self.findFreshItems, feed)
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
            if result.feed.title:
                print "%s: Title: %s " % (feed["handle"],
                                          repr(result.feed.title))
        else:
            print "%s: Not a valid feed." % feed["handle"]

        if result.bozo:
            print "%s: Bozo flag raised: %s: %s" % (feed["handle"],
                                                    repr(result.bozo_exception),
                                                    result.bozo_exception)

        for entry in result.entries:
            if not entry.has_key('id'):
                entry.id = entry.link

        return result

    def publishEntries(self, entries, feed):
        for entry in entries:
            if entry.has_key('id'):
                print "  id: %s" % entry.id
            if entry.has_key('title'):
                print "  title (%s): %s" % \
                      (entry.title_detail.type,
                       repr(entry.title_detail.value))

        #reactor.callLater(0, self._publishEntry, entry, feed)
        self._publishEntries(entries, feed)

    def _publishEntries(self, entries, feed):
        print "publishing items"
        
        iq = client.IQ(self.xmlstream, 'set')
        iq['to'] = 'pubsub.ik.nu'
        iq['from'] = self.xmlstream.authenticator.streamHost
        iq.addElement(('http://jabber.org/protocol/pubsub', 'pubsub'))
        iq.pubsub.addElement('publish')
        iq.pubsub.publish["node"] = 'mimir/news/%s' % feed["handle"]

        for entry in entries:
            item = iq.pubsub.publish.addElement('item')
            item["id"] = entry.id
            news = item.addElement(('mimir:news', 'news'))
            if entry.has_key('title'):
                content = entry.title
                if entry.title_detail.type == 'text/plain':
                    content = domish.escapeToXml(content)
                news.addElement('title', content=content)
            if entry.has_key('link'):
                news.addElement('link', content=entry.link)

            # Find a description. First try full text, then summary.
            content = None
            if entry.has_key('content'):
                content = entry.content[0].value
                type = entry.content[0].type
            elif entry.has_key('summary'):
                content = entry.summary
                type = entry.summary_detail.type
            if content:
                if type == 'text/plain':
                    content = domish.escapeToXml(content)
                news.addElement('description', content=content)

        iq.send()

    def findFreshItems(self, f, feed):
        cache = feed.get('cache', {})

        new_cache = {}
        new_entries = []
        for entry in reversed(f.entries):
            if cache.has_key(entry.id):
                if cache[entry.id] != entry:
                    print "%s: Found updated item" % feed["handle"]
                    new_entries.append(entry)
            else:
                print "%s: Found new item:" % feed["handle"]
                new_entries.append(entry)

            new_cache[entry.id] = entry

        if new_entries:
            self.publishEntries(new_entries, feed)
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
        print "RECV: %s" % repr(buf)

    def rawDataOut(self, buf):
        print "SEND: %s" % repr(buf)

def makeService(config):
    sm = component.buildServiceManager(config["jid"], config["secret"],
            ("tcp:%s:%s" % (config["rhost"], config["rport"])))

    if config["verbose"]:
        LogService().setServiceParent(sm)

    AggregatorService().setServiceParent(sm)

    return sm
