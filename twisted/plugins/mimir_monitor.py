# Copyright (c) 2005-2008 Ralph Meijer
# See LICENSE for details

try:
    from twisted.application.service import ServiceMaker
except ImportError:
    from twisted.scripts.mktap import _tapHelper as ServiceMaker

mimirMonitor = ServiceMaker(
        "Mimir Monitor",
        "mimir.monitor.tap",
        "Mimir News and Presence Monitor",
        "monitor")
