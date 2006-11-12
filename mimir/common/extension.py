# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

from zope.interface import Interface, Attribute, implements

class IExtensionProtocol(Interface):
    """
    XMPP subprotocol interface.

    Objects that provide this interface can be added to a stream manager to
    handle of (part of) an XMPP extension protocol.
    """

    manager = Attribute("""XML stream manager""")
    xmlstream = Attribute("""The managed XML stream""")

    def connectionMade():
        """
        A connection over the underlying transport of the XML stream has been
        established.

        At this point, no traffic has been exchanged over the XML stream. This
        method can be used to change properties of the XML Stream, its
        authenticator or the stream manager prior to stream initialization
        (including authentication).
        """

    def connectionInitialized():
        """
        The XML stream has been initialized.

        At this point, authentication was successful, and XML stanzas can be
        exchanged over the XML stream C{self.xmlstream}. This method can be
        used to setup observers for incoming stanzas.
        """

    def connectionLost():
        """
        The XML stream has been closed.

        Subsequent use of C{self.parent.send} will result in data being queued
        until a new connection has been established.
        """

class ExtensionProtocol(object):
    implements(IExtensionProtocol)

    def connectionMade(self):
        pass

    def connectionInitialized(self):
        pass

    def connectionLost(self):
        pass

    def send(self, obj):
        """
        Send data over the managed XML stream.

        @note: The stream manager maintains a queue for data sent using this
               method when there is no current established XML stream. This
               data is then sent as soon as a new stream has been established
               and initialized. Subsequently, L{connectionInitialized} will be
               called again. If this queueing is not desired, use C{send} on
               the XmlStream object (passed to L{componentConnected}) directly.

        @param obj: data to be sent over the XML stream. This is usually an
                    object providing L{domish.IElement}, or serialized XML. See
                    L{xmlstream.XmlStream} for details.
        """

        self.manager.send(obj)
