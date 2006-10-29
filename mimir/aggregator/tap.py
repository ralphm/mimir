# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Create a aggregation service.
"""

from twisted.python import usage
from twisted.words.protocols.jabber import component

from mimir.aggregator.aggregator import AggregatorService
from mimir.common.fallback import FallbackService
from mimir.common.log import LogService

class Options(usage.Options):
    optParameters = [
        ('feeds', None, 'feeds', 'File that holds the list of feeds'),
        ('jid', None, 'aggregator', 'JID of this component'),
        ('secret', None, 'secret', 'Secret to connect to upstream server'),
        ('rhost', None, '127.0.0.1', 'Upstream server address'),
        ('rport', None, '5347', 'Upstream server port'),
    ]

    optFlags = [
        ('verbose', 'v', 'Show traffic'),
    ]
    
def makeService(config):
    sm = component.buildServiceManager(config["jid"], config["secret"],
            ("tcp:%s:%s" % (config["rhost"], config["rport"])))

    # wait for no more than 15 minutes to try to reconnect
    sm.getFactory().maxDelay = 900

    FallbackService().setServiceParent(sm)

    if config["verbose"]:
        LogService().setServiceParent(sm)

    ag = AggregatorService(config['feeds'])
    ag.setServiceParent(sm)

    return sm
