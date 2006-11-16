from zope.interface import Interface, implements
from twisted.words.protocols.jabber import jid, xmlstream
from twisted.words.xish import domish
from mimir.common import extension

NS_PUBSUB = 'http://jabber.org/protocol/pubsub'
NS_PUBSUB_OWNER = 'http://jabber.org/protocol/pubsub#owner'
NS_PUBSUB_EVENT = 'http://jabber.org/protocol/pubsub#event'

class Item(domish.Element):
    """
    Publish subscribe item.

    This behaves like an object providing L{domish.IElement}.
    
    Item payload can be added using C{addChild} or C{addRawXml}, or using the
    C{payload} keyword argument to C{__init__}.
    """

    def __init__(self, id=None, payload=None):
        """
        @param id: optional item identifier
        @type id: L{unicode}
        @param payload: optional item payload. Either as a domish element, or
                        as serialized XML.
        @type payload: object providing L{domish.IElement} or L{unicode}.
        """

        domish.Element.__init__(self, (None, 'item'))
        if id is not None:
            self['id'] = id
        if payload is not None:
            if isinstance(payload, basestring):
                self.addRawXml(payload)
            else:
                self.addChild(payload)

class PubSubRequest(xmlstream.IQ):
    """
    Base class for publish subscribe user requests.

    @cvar namespace: request namespace
    @cvar verb: request verb
    @cvar method: type attribute of the IQ request. Either C{'set'} or C{'get'}
    @ivar command: command element of the request. This is the direct child of
                   the C{pubsub} element in the C{namespace} with the name
                   C{verb}.
    """

    namespace = NS_PUBSUB
    method = 'set'

    def __init__(self, xs):
        xmlstream.IQ.__init__(self, xs, self.method)
        self.addElement((self.namespace, 'pubsub'))

        self.command = self.pubsub.addElement(self.verb)

class CreateNode(PubSubRequest):
    verb = 'create'

    def __init__(self, xs, node=None):
        PubSubRequest.__init__(self, xs)
        if node:
            self.command["node"] = node

class DeleteNode(PubSubRequest):
    verb = 'delete'
    def __init__(self, xs, node):
        PubSubRequest.__init__(self, xs)
        self.command["node"] = node

class Subscribe(PubSubRequest):
    verb = 'subscribe'

    def __init__(self, xs, node, subscriber):
        PubSubRequest.__init__(self, xs)
        self.command["node"] = node
        self.command["jid"] = subscriber.full()

class Publish(PubSubRequest):
    verb = 'publish'

    def __init__(self, xs, node):
        PubSubRequest.__init__(self, xs)
        self.command["node"] = node

    def addItem(self, id=None, payload=None):
        item = self.command.addElement("item")
        item.addChild(payload)

        if id is not None:
            item["id"] = id

        return item

class SubscriptionPending(Exception):
    """
    Raised when the requested subscription is pending acceptance.
    """

class SubscriptionUnconfigured(Exception):
    """
    Raised when the requested subscription needs to be configured before
    becoming active.
    """

class IPubSubClient(Interface):

    def itemsReceived(notifier, node, items):
        """
        Called when items have been received from a node.

        @param notifier: the entity from which the notification was received.
        @type notifier: L{jid.JID}
        @param node: identifier of the node the items belong to.
        @type node: C{unicode}
        @param items: list of received items as domish elements.
        @type items: C{list} of L{domish.Element}
        """

    def createNode(node=None):
        """
        Create a new publish subscribe node.

        @param node: optional suggestion for the new node's identifier. If
                     omitted, the creation of an instant node will be
                     attempted.
        @type node: L{unicode}
        @return: a deferred that fires with the identifier of the newly created
                 node. Note that this can differ from the suggested identifier
                 if the publish subscribe service chooses to modify or ignore
                 the suggested identifier.
        @rtype: L{defer.Deferred}
        """

    def deleteNode(node):
        """
        Delete a node.

        @param node: identifier of the node to be deleted.
        @type node: L{unicode}
        @rtype: L{defer.Deferred}
        """

    def subscribe(node, subscriber):
        """
        Subscribe to a node with a given JID.

        @param node: identifier of the node to subscribe to.
        @type node: L{unicode}
        @param subscriber: JID to subscribe to the node.
        @type subscriber: L{jid.JID}
        @rtype: L{defer.Deferred}
        """

    def publish(node, items=[]):
        """
        Publish to a node.

        Node that the C{items} parameter is optional, because so-called
        transient, notification-only nodes do not use items and publish
        actions only signify a change in some resource.

        @param node: identifier of the node to publish to.
        @type node: L{unicode}
        @param items: list of item elements.
        @type items: L{list} of L{Item}
        @rtype: L{defer.Deferred}
        """

class PubSubClient(extension.XMPPHandler):
    """
    Publish subscribe client protocol.

    @param service: JID of the target publish subscribe service.
    @type service: L{jid.JID}
    """

    implements(IPubSubClient)

    def __init__(self, service):
        self.service = service

    def connectionInitialized(self):
        self.xmlstream.addObserver('/message/event[@xmlns="%s"]/items' %
                                   NS_PUBSUB_EVENT, self._onItems)

    def _onItems(self, message):
        try:
            notifier = jid.JID(message["from"])
            node = message.event.items["node"]
        except KeyError:
            return

        items = [element for element in message.event.items.elements()
                         if element.name == 'item']

        self.itemsReceived(notifier, node, items)

    def itemsReceived(self, notifier, node, items):
        pass

    def createNode(self, node=None):
        request = CreateNode(self.xmlstream, node)
       
        def cb(iq):
            try:
                new_node = iq.pubsub.create["node"]
            except AttributeError:
                # the suggested node identifier was accepted
                new_node = node
            return new_node

        return request.send(self.service).addCallback(cb)

    def deleteNode(self, node):
        return DeleteNode(self.xmlstream, node).send(self.service)

    def subscribe(self, node, subscriber):
        request = Subscribe(self.xmlstream, node, subscriber)
       
        def cb(iq):
            subscription = iq.pubsub.subscription["subscription"]

            if subscription == 'pending':
                raise SubscriptionPending
            elif subscription == 'unconfigured':
                raise SubscriptionUnconfigured
            else:
                # we assume subscription == 'subscribed'
                # any other value would be invalid, but that should have
                # yielded a stanza error.
                return None

        return request.send(self.service).addCallback(cb)

    def publish(self, node, items=[]):
        request = Publish(self.xmlstream, node)
        for item in items:
            request.command.addChild(item)

        return request.send(self.service)
