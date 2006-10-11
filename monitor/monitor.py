from twisted.application.service import Application
from twisted.enterprise import adbapi
from twisted.words.protocols.jabber import jid
import client, news, presence, service

config = {
    'jid': jid.JID('mimir@ik.nu/news_monitor'),
    'secret': '35t120p',
    'dbuser': 'ralphm',
    'dbname': 'mimir'
}

class LogService(service.Service):

    def connectionMade(self, xmlstream):
        xmlstream.rawDataInFn = self.rawDataIn
        xmlstream.rawDataOutFn = self.rawDataOut

    def rawDataIn(self, buf):
        print "RECV: %s" % unicode(buf, 'utf-8').encode('ascii', 'replace')

    def rawDataOut(self, buf):
        print "SEND: %s" % unicode(buf, 'utf-8').encode('ascii', 'replace')

application = Application("test")
clientService = client.buildClientServiceManager(config['jid'],
                                                 config['secret'])
clientService.factory.maxDelay = 900
clientService.setServiceParent(application)
LogService().setServiceParent(clientService)
dbpool = adbapi.ConnectionPool('pyPgSQL.PgSQL',
                               user=config["dbuser"],
                               database=config["dbname"],
                               client_encoding='utf-8',
                               cp_min = 1,
                               cp_max = 1
                               )
ms = presence.Storage(dbpool)
presenceMonitor = presence.RosterMonitor(ms)
presenceMonitor.setServiceParent(clientService)
newsMonitor = news.Monitor(presenceMonitor, dbpool)
newsMonitor.setServiceParent(clientService)
