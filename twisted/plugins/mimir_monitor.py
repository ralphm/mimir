# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

from twisted.scripts.mktap import _tapHelper

MimirMonitor = _tapHelper(
        "Mimir Monitor",
        "mimir.monitor.tap",
        "Mimir News and Presence Monitor",
        "monitor")
