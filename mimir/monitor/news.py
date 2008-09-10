# -*- test-case-name: mimir.monitor.test.test_news -*-
#
# Copyright (c) 2005-2008 Ralph Meijer
# See LICENSE for details

import re, time

import feedparser, simplejson

from zope.interface import Interface, implements

from twisted.application import service
from twisted.internet import reactor
from twisted.python import components, failure
from twisted.words.xish import domish

from wokkel import pubsub
from wokkel.iwokkel import IXMPPHandler

SGMLTAG = re.compile('<.+?>', re.DOTALL)
NS_ATOM = 'http://www.w3.org/2005/Atom'

class FeedParserEncoder(simplejson.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, time.struct_time):
            return tuple(obj)
        elif isinstance(obj, Exception):
            return failure.Failure(obj).getTraceback()
        else:
            return simplejson.JSONEncoder.default(self, obj)

class NoNotify(Exception):
    pass

class INewsService(Interface):

    def process(channel, items):
        """
        Process new items for channel

        @param items: atom entries
        @type items: L{domish.Element}
        """

class NewsService(service.Service):

    implements(INewsService)

    def __init__(self, presenceMonitor, dbpool):
        self._dbpool = dbpool
        presenceMonitor.register_callback(self.onPresenceChange)

    def error(self, failure):
        print failure

    def onPresenceChange(self, entity, available, show):
        if available:
            if show not in ['away', 'xa', 'dnd', 'chat']:
                show = 'online'
        else:
            show = 'offline'

        print "  presence change to %s for %r", (show, entity.full())
        reactor.callLater(5, self.pageNotify, entity, show)

    def pageNotify(self, entity, show):
        d = self._dbpool.runInteraction(self._checkNotify, entity, show)
        d.addCallback(self._doNotify, entity)
        d.addCallback(self._setNotified)
        d.addErrback(lambda failure: failure.trap(NoNotify))
        d.addErrback(self.error)

    def _checkNotify(self, cursor, entity, show):
        cursor.execute("""SELECT user_id, message_type, ssl,
                                 count(news_id) as count
                          FROM auth_user
                          NATURAL JOIN news_prefs
                          NATURAL JOIN news_notify_presences
                          NATURAL JOIN news_page
                          NATURAL JOIN news_flags
                          NATURAL JOIN news
                          WHERE jid=%s AND
                                NOT suspended AND
                                presence=%s AND
                                NOT notified AND
                                date>last_visit
                          GROUP BY user_id, message_type, ssl""",
                       (entity.userhost(),
                        show))
        result = cursor.fetchone()

        if not result:
            return failure.Failure(NoNotify())

        return result

    def _doNotify(self, result, entity):
        userId, messageType, ssl, count = result

        title = u'New news on Mim\xedr!'
        link = "%s://mimir.ik.nu/news" % (ssl and 'https' or 'http')
        description = 'There '
        if count == 1:
            description += 'is 1 new item'
        else:
            description += 'are %s new items' % count
        description += ' on your news page'

        self.notifier.sendNotification(entity.full(), True, messageType,
                                       title, link, description)
        return userId

    def _setNotified(self, userId):
        return self._dbpool.runOperation("""UPDATE news_page SET notified=true
                                            WHERE user_id=%s""", userId)

    def process(self, channel, items):
        print "Got entries: %r" % items
        d = self._dbpool.runInteraction(self._processItems, channel, items)
        d.addCallback(self.notify)
        d.addErrback(self.error)

    def _processItems(self, cursor, channel, items):

        # Get channel title
        cursor.execute("SELECT title from channels WHERE channel=%s",
                       channel)
        title = cursor.fetchone()[0]

        print "Channel title: %r" % title

        feedDocument = domish.Element((NS_ATOM, 'feed'))
        for item in items:
            feedDocument.addChild(item)

        feed = feedparser.parse(feedDocument.toXml().encode('utf-8'))
        entries = feed.entries

        # Get notify list, including preferences
        cursor.execute("""SELECT user_id, jid, notify,
                                 description_in_notify, message_type,
                                 store_offline, notify_items
                          FROM news_prefs
                            NATURAL JOIN news_subscriptions
                            NATURAL JOIN news_notify
                          WHERE NOT suspended AND channel=%s""",
                       channel)

        notifyList = cursor.fetchall()

        # split notify list into a list of entities that are to be notified
        # and a list of entities that will get items marked as unread
        notifications = []
        markUnread = []
        for userId, jid, notify, descriptionInNotify, messageType, \
            storeOffline, notifyItems in \
                notifyList:
            if notify and notifyItems:
                notifications.append((jid,
                                      descriptionInNotify,
                                      messageType))
            elif storeOffline:
                markUnread.append(userId)

        # store items and mark unread
        notifyItems = []
        for entry in entries:
            newsId = self._storeItem(cursor, channel, entry)
            if newsId:
                for userId in markUnread:
                    cursor.execute("""INSERT INTO news_flags
                                      (user_id, news_id, unread) VALUES
                                      (%s, %s, true)""",
                                   (userId, newsId))
                    cursor.execute("""UPDATE news_page SET notified=false
                                      WHERE user_id=%s""",
                                   userId)

                notifyItems.append(entry)
        return (title, notifications, notifyItems)

    def _extractBasics(self, entry):
        if 'title' in entry:
            title = entry.title

            if 'source' in entry and 'title' in entry.source:
                content = "%s: %s" % (entry.source.title, title)

            if entry.title_detail == 'text/plain':
                title = feedparser._xmlescape(title)
        else:
            title = u''

        if 'link' in entry:
            link = entry.get('feedburner_origlink', entry.link)
        else:
            link = u''

        # Find a description. First try full text, then summary.
        content = None
        if 'content' in entry and entry.content[0].value:
            content = entry.content[0]
        elif 'summary' in entry:
            content = entry.summary_detail

        if content:
            value = content.value
            if content.type == 'text/plain':
                value = feedparser._xmlescape(value)
            description = value
        else:
            description = u''

        date = None
        for attribute in 'updated', 'published', 'created':
            if attribute in entry:
                date = getattr(entry, '%s_parsed' % attribute)

        date = time.strftime("%Y-%m-%d %H:%M:%Sz", date or time.gmtime())

        return title, link, description, date

    def _storeItem(self, cursor, channel, entry):
        title, link, description, date = self._extractBasics(entry)
        json = simplejson.dumps(entry, cls=FeedParserEncoder)

        print "Storing item: %r" % entry.id

        cursor.execute("""UPDATE news
                          SET title=%s, description=%s, date=%s, parsed=%s
                          WHERE channel=%s AND link=%s""",
                       (title, description, date, json, channel, link))

        if cursor.rowcount == 1:
            print "UPDATE"
            return None

        cursor.execute("""INSERT INTO news
                          (channel, title, link, description, date, parsed)
                          VALUES
                          (%s, %s, %s, %s, %s, %s)""",
                       (channel, title, link, description, date, json))

        print "INSERT",

        cursor.execute("""SELECT news_id FROM news
                          WHERE channel=%s and link=%s""",
                          (channel, link))

        newsId = cursor.fetchone()[0]

        print newsId
        return newsId

    def notify(self, result):
        channelTitle, notifications, entries = result

        for entry in entries:
            title = "%s: %s" % (channelTitle,
                                entry.get('title', u'-- no title --'))
            link = entry.get('link', '')
            description = entry.get('summary')

            if description:
                description = SGMLTAG.sub('', description)
                description = domish.unescapeFromXml(description)
                description = description.rstrip() or None

            for jid, descriptionInNotify, messageType in notifications:
                self.notifier.sendNotification(jid, descriptionInNotify,
                                               messageType, title, link,
                                               description)

class XMPPHandlerFromService(pubsub.PubSubClient):

    def __init__(self, service):
        self.service = service

    def sendNotification(self, jid, descriptionInNotify, messageType,
                         title, link, description):

        message = domish.Element((None, 'message'))
        message['to'] = jid
        message['type'] = messageType

        if messageType == 'chat':
            body = "%s\n%s" % (title, link)
            if description and descriptionInNotify:
                body += "\n\n%s\n\n" % description

            message.addElement('body', None, body)
        elif messageType == 'headline':
            message.addElement('subject', None, title)
            if description:
                message.addElement('body', None, description)
            oob = message.addElement(('jabber:x:oob', 'x'))
            oob.addElement('url', None, link)
            oob.addElement('desc', None, title)

        print "Sending: %r" % message.toXml()
        self.send(message)

    def itemsReceived(self, event):
        m = re.match(r"^mimir/news/(.+)$", event.nodeIdentifier)

        if not m:
            return

        channel = m.group(1)

        entries = (item.entry for item in event.items
                              if item.entry and item.entry.uri == NS_ATOM)

        self.service.process(channel, entries)

components.registerAdapter(XMPPHandlerFromService,
                           INewsService,
                           IXMPPHandler)
