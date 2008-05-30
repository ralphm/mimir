# Copyright (c) 2005-2008 Ralph Meijer
# See LICENSE for details

try:
    from twisted.application.service import ServiceMaker
except ImportError:
    from twisted.scripts.mktap import _tapHelper as ServiceMaker

mimirAggregator = ServiceMaker(
        "Mimir Aggregator",
        "mimir.aggregator.tap",
        "Mimir Feed Aggregator and Feeder",
        "aggregator")
