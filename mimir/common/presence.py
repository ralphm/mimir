from twisted.words.protocols.jabber import jid
from twisted.words.xish import domish

from mimir.common import extension

NS_XML = 'http://www.w3.org/XML/1998/namespace'

class Presence(domish.Element):
    def __init__(self, to=None, type=None):
        domish.Element.__init__(self, (None, "presence"))
        if type:
            self["type"] = type

        if to is not None:
            self["to"] = to.full()

class AvailablePresence(Presence):
    def __init__(self, to=None, show=None, statuses=None, priority=0):
        Presence.__init__(self, to, type=None)

        if show in ['away', 'xa', 'chat', 'dnd']:
            self.addElement('show', content=show)

        if statuses is not None:
            for lang, status in statuses.iteritems():
                s = self.addElement('status', content=status)
                if lang:
                    s[(NS_XML, "lang")] = lang

        if priority != 0:
            self.addElement('priority', int(priority))

class UnavailablePresence(Presence):
    def __init__(self, to=None, statuses=None):
        Presence.__init__(self, to, type='unavailable')

        if statuses is not None:
            for lang, status in statuses.iteritems():
                s = self.addElement('status', content=status)
                if lang:
                    s[(NS_XML, "lang")] = lang

class PresenceHandler(extension.XMPPHandler):

    def connectionInitialized(self):
        self.xmlstream.addObserver('/presence', self._onPresence)

    def _getStatuses(self, presence):
        statuses = {}
        for element in presence.elements():
            if element.name == 'status':
                lang = element.getAttribute((NS_XML, 'lang'))
                text = unicode(element)
                statuses[lang] = text
        return statuses

    def _onPresence(self, presence):
        type = presence.getAttribute("type", "available")
        try:
            handler = getattr(self, '_onPresence%s' % (type.capitalize()))
        except AttributeError:
            return
        else:
            handler(presence)

    def _onPresenceAvailable(self, presence):
        entity = jid.JID(presence["from"])

        show = unicode(presence.show or '')
        if show not in ['away', 'xa', 'chat', 'dnd']:
            show = None

        statuses = self._getStatuses(presence)

        try:
            priority = int(unicode(presence.priority or '')) or 0
        except ValueError:
            priority = 0

        self.availableReceived(entity, show, statuses, priority)

    def _onPresenceUnavailable(self, presence):
        entity = jid.JID(presence["from"])

        statuses = self._getStatuses(presence)

        self.unavailableReceived(entity, statuses)

    def _onPresenceSubscribed(self, presence):
        self.subscribedReceived(jid.JID(presence["from"]))

    def _onPresenceUnsubscribed(self, presence):
        self.unsubscribedReceived(jid.JID(presence["from"]))

    def _onPresenceSubscribe(self, presence):
        self.subscribeReceived(jid.JID(presence["from"]))

    def _onPresenceUnsubscribe(self, presence):
        self.unsubscribeReceived(jid.JID(presence["from"]))

    def availableReceived(self, entity, show=None, statuses=None, priority=0):
        """
        Available presence was received.

        @param entity: entity from which the presence was received.
        @type entity: {jid.JID}
        @param show: detailed presence information. One of C{'away'}, C{'xa'},
                     C{'chat'}, C{'dnd'} or C{None}.
        @type show: C{str} or C{NoneType}
        @param statuses: dictionary of natural language descriptions of the
                         availability status, keyed by the language
                         descriptor. A status without a language
                         specified, is keyed with C{None}.
        @type statuses: C{dict}
        @param priority: priority level of the resource.
        @type priority: C{int}
        """

    def unavailableReceived(self, entity, statuses=None, priority=0):
        """
        Unavailable presence was received.

        @param entity: entity from which the presence was received.
        @type entity: {jid.JID}
        @param statuses: dictionary of natural language descriptions of the
                         availability status, keyed by the language
                         descriptor. A status without a language
                         specified, is keyed with C{None}.
        @type statuses: C{dict}
        """

    def subscribedReceived(self, entity):
        """
        Subscription approval confirmation was received.

        @param entity: entity from which the confirmation was received.
        @type entity: {jid.JID}
        """

    def unsubscribedReceived(self, entity):
        """
        Unsubscription confirmation was received.

        @param entity: entity from which the confirmation was received.
        @type entity: {jid.JID}
        """

    def subscribeReceived(self, entity):
        """
        Subscription request was received.

        @param entity: entity from which the request was received.
        @type entity: {jid.JID}
        """

    def unsubscribedReceived(self, entity):
        """
        Unsubscription request was received.

        @param entity: entity from which the request was received.
        @type entity: {jid.JID}
        """

    def available(self, entity=None, show=None, statuses=None, priority=0):
        """
        Send available presence.
        
        @param entity: optional entity to which the presence should be sent.
        @type entity: {jid.JID}
        @param show: optional detailed presence information. One of C{'away'},
                     C{'xa'}, C{'chat'}, C{'dnd'}.
        @type show: C{str}
        @param statuses: dictionary of natural language descriptions of the
                         availability status, keyed by the language
                         descriptor. A status without a language
                         specified, is keyed with C{None}.
        @type statuses: C{dict}
        @param priority: priority level of the resource.
        @type priority: C{int}
        """
        self.send(AvailablePresence(entity, show, statuses, priority))

    def unavailable(self, entity, statuses=None):
        """
        Send unavailable presence.
        
        @param entity: optional entity to which the presence should be sent.
        @type entity: {jid.JID}
        @param statuses: dictionary of natural language descriptions of the
                         availability status, keyed by the language
                         descriptor. A status without a language
                         specified, is keyed with C{None}.
        @type statuses: C{dict}
        """
        self.send(AvailablePresence(entity, statuses))

    def subscribe(self, entity):
        """
        Send subscription request

        @param entity: entity to subscribe to.
        @type entity: {jid.JID}
        """
        self.send(Presence(to=entity, type='subscribe'))

    def unsubscribe(self, entity):
        """
        Send unsubscription request

        @param entity: entity to unsubscribe from.
        @type entity: {jid.JID}
        """
        self.send(Presence(to=entity, type='unsubscribe'))

    def subscribed(self, entity):
        """
        Send subscription confirmation.

        @param entity: entity that subscribed.
        @type entity: {jid.JID}
        """
        self.send(Presence(to=entity, type='subscribed'))

    def unsubscribed(self, entity):
        """
        Send unsubscription confirmation.

        @param entity: entity that unsubscribed.
        @type entity: {jid.JID}
        """
        self.send(Presence(to=entity, type='unsubscribed'))
