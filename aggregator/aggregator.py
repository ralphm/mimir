import fetcher
import feedparser
import xmpp_error
from twisted.python import log
from twisted.internet import reactor, defer
from twisted.persisted import sob
from twisted.xish import domish
from twisted.words.protocols.jabber import component, client

INTERVAL=1800

class AggregatorService(component.Service):
    agent = "MimirAggregator/0.2 (http://mimir.ik.nu/)"

    def startService(self):
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
        for handle, url in feed_list:
            if feeds.has_key(handle):
                if url != feeds[handle]['url']:
                    feeds[handle]['url'] = url
                self.feeds[handle] = feeds[handle]
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
        
        list = []
        for feed in self.feeds.itervalues():
            list.append(self.start(feed))
        d = defer.DeferredList(list)

    def iqFallback(self, iq):
        if iq.handled == True:
            return

        self.send(xmpp_error.error_from_iq(iq, 'service-unavailable'))

    def start(self, feed):
        d = fetcher.getFeed(feed['url'], self.agent)
        d.addCallback(self.workOnPage, feed)
        d.addCallback(self.parseFeed, feed)
        d.addCallback(self.findFreshItems, feed)
        d.addErrback(self.notModified, feed)
        d.addErrback(self.munchError, feed)
        d.addBoth(self.reschedule, feed)
        return d

    def workOnPage(self, result, feed):
        handle = feed['handle']
        print "%s: Got feed" % handle
        data, url = result
        if url != feed['url']:
            print "%s: Feed's location changed permanently to %s" % \
                  (handle, url)
            feed['url'] = url

        return data

    def parseFeed(self, data, feed):
        f = feedparser.parse(data)

        print "%s: Title: %s " % (feed["handle"], f.feed.title.encode('utf-8'))

        for entry in f.entries:
            if not entry.has_key('id'):
                entry.id = entry.link

        return f

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
        reactor.callLater(INTERVAL, self.start, feed)

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
