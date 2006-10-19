# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Create a aggregation service.
"""

from twisted.python import usage
from twisted.words.protocols.jabber import component

from mimir.aggregator.aggregator import AggregatorService
from mimir.common.log import LogService

class Options(usage.Options):
    optParameters = [
        ('feeds', None, 'feeds', 'File that holds the list of feeds'),
        ('jid', None, None),
        ('secret', None, 'secret'),
        ('rhost', None, '127.0.0.1'),
        ('rport', None, '5347'),
    ]

    optFlags = [
        ('verbose', 'v', 'Show traffic'),
    ]
    
def makeService(config):
    sm = component.buildServiceManager(config["jid"], config["secret"],
            ("tcp:%s:%s" % (config["rhost"], config["rport"])))

    # wait for no more than 15 minutes to try to reconnect
    sm.getFactory().maxDelay = 900

    if config["verbose"]:
        LogService().setServiceParent(sm)

    AggregatorService(config['feeds']).setServiceParent(sm)

    return sm
