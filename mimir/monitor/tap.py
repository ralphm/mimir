# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Create a monitor service.
"""

from twisted.enterprise import adbapi
from twisted.python import usage
from twisted.words.protocols.jabber import jid

from mimir.common.log import LogService
from mimir.monitor import client, news, presence

class Options(usage.Options):
    optParameters = [
        ('jid', None, None),
        ('secret', None, None),
        ('dbuser', None, None),
        ('dbname', None, 'mimir'),
    ]

    optFlags = [
        ('verbose', 'v', 'Show traffic'),
    ]

    def postOptions(self):
        try:
            self['jid'] = jid.JID(self['jid'])
        except jid.InvalidFormat:
            raise usage.UsageError("'%(jid)s' is not a valid Jabber ID" % self)
    
def makeService(config):
    clientService = client.buildClientServiceManager(config['jid'],
                                                     config['secret'])
    clientService.factory.maxDelay = 900

    if config["verbose"]:
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
    
    return clientService
