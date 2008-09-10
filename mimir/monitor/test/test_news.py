# Copyright (c) 2005-2008 Ralph Meijer
# See LICENSE for details

"""
Tests for L{mimir.monitor.news}.
"""

from zope.interface import verify
from twisted.trial import unittest

from wokkel import iwokkel

from mimir.monitor import news

class XMPPHandlerFromServiceTest(unittest.TestCase):

    def test_interface(self):
        """
        Do instances of L{news.XMPPHandlerFromService} provide
        L{iwokkel.IPubSubClient}?
        """
        verify.verifyObject(iwokkel.IPubSubClient,
                            news.XMPPHandlerFromService(None))

