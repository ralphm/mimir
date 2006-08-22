# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Create a aggregation service.
"""

from twisted.python import usage
import aggregator

class Options(usage.Options):
    optParameters = [
        ('jid', None, None),
        ('secret', None, None),
        ('rhost', None, '127.0.0.1'),
        ('rport', None, '6000'),
    ]

    optFlags = [
        ('verbose', 'v', 'Show traffic'),
    ]
    
def makeService(config):
    return aggregator.makeService(config)
