# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Create a aggregation service.
"""

from twisted.application import service
from twisted.python import usage

from mimir.aggregator import aggregator
from mimir.common.fallback import FallbackHandler
from mimir.common import extension, component, pubsub

class Options(usage.Options):
    optParameters = [
        ('feeds', None, 'feeds', 'File that holds the list of feeds'),
        ('jid', None, 'aggregator', 'JID of this component'),
        ('secret', None, 'secret', 'Secret to connect to upstream server'),
        ('rhost', None, '127.0.0.1', 'Upstream server address'),
        ('rport', None, '5347', 'Upstream server port'),
        ('service', None, None, 'Publish subscribe service JID'),
    ]

    optFlags = [
        ('verbose', 'v', 'Show traffic'),
    ]

    def postOptions(self):
        try:
            self['rport'] = int(self['rport'])
        except ValueError:
            pass

    
def makeService(config):
    s = service.MultiService()

    # create XMPP external component
    cs = component.Component(config['rhost'], config['rport'],
                             config['jid'], config['secret'])
    cs.setServiceParent(s)

    # wait for no more than 15 minutes to try to reconnect
    cs.factory.maxDelay = 900

    if config["verbose"]:
        cs.logTraffic = True
    cs.addHandler(FallbackHandler())

    # set up publish-subscribe client handler
    publisher = pubsub.PubSubClient(config['service'])
    cs.addHandler(publisher)

    # create aggregation service 
    ag = aggregator.AggregatorService(config['feeds'])
    ag.setServiceParent(s)

    # set up feed handler from publisher
    ag.handler = aggregator.IFeedHandler(publisher)

    # set up XMPP handler to interface with aggregator
    cs.addHandler(extension.IXMPPHandler(ag))

    return s
