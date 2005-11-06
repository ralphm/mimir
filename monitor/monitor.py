#!/usr/local/bin/python

from twisted.words.protocols.jabber.client import basicClientFactory
from twisted.words.protocols.jabber import jid, xmlstream
from twisted.xish import domish
from twisted.internet import reactor
import presence
import news

config = {
    'user': 'mimir',
    'host': 'ik.nu',
    'resource': 'news_monitor',
    'secret': '35t120p',
    'dbuser': 'ralphm',
    'dbname': 'mimir'
}

class Log:

    def connected(self, xmlstream):
        xmlstream.rawDataInFn = self.rawDataIn
        xmlstream.rawDataOutFn = self.rawDataOut

    def rawDataIn(self, buf):
        print "RECV: %s" % unicode(buf, 'utf-8').encode('ascii', 'replace')

    def rawDataOut(self, buf):
        print "SEND: %s" % unicode(buf, 'utf-8').encode('ascii', 'replace')

log = Log()
ms = presence.Storage(config["dbuser"], config["dbname"])
presence_monitor = presence.RosterMonitor(ms)
news_monitor = news.Monitor(presence_monitor, config["dbuser"], config["dbname"])
cf = basicClientFactory(jid.JID(tuple = (config["user"],
                                         config["host"],
                                         config["resource"])),
                        config["secret"])
cf.addBootstrap(xmlstream.STREAM_AUTHD_EVENT, log.connected)
cf.addBootstrap(xmlstream.STREAM_AUTHD_EVENT, presence_monitor.connected)
cf.addBootstrap(xmlstream.STREAM_AUTHD_EVENT, news_monitor.connected)
reactor.connectTCP(config["host"], 5222, cf)
reactor.run()
