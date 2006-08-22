# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

from twisted.scripts.mktap import _tapHelper

MimirAggregator = _tapHelper(
        "Mimir Aggregator",
        "aggregator.tap",
        "Mimir Feed Aggregator and Feeder",
        "aggregator")


