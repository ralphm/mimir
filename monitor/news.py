from twisted.application import service
from twisted.enterprise import adbapi
from twisted.python import failure
from twisted.internet import reactor
from twisted.words.xish import domish
import re

SGMLTAG = re.compile('<.+?>', re.DOTALL)

domish.Element.__unicode__ = domish.Element.__str__

class NoNotify(Exception):
    pass

class Monitor(service.Service):
    def __init__(self, presence_monitor, user, database):
        self._dbpool = adbapi.ConnectionPool('pyPgSQL.PgSQL',
                                            user=user,
                                            database=database,
                                            client_encoding='utf-8')
        presence_monitor.register_callback(self.onPresenceChange)

    def connected(self, xmlstream):
        self.xmlstream = xmlstream
        xmlstream.addObserver('/message/event[@xmlns="http://jabber.org/protocol/pubsub#event"]/items', self.onEvent)


    def error(self, failure):
        print failure

    def onPresenceChange(self, entity, available, show):
        if available:
            if show not in ['away', 'xa', 'dnd', 'chat']:
                show = 'online'
        else:
            show = 'offline'

        print "  presence change to %s for %s", (show, repr(entity.full()))
        reactor.callLater(5, self.page_notify, entity, show)

    def page_notify(self, entity, show):
        d = self._dbpool.runInteraction(self._check_notify, entity, show)
        d.addCallback(self._do_notify, entity)
        d.addCallback(self._set_notified)
        d.addErrback(lambda failure: failure.trap(NoNotify))
        d.addErrback(self.error)

    def _check_notify(self, cursor, entity, show):
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

    def _do_notify(self, result, entity):
        user_id, message_type, ssl, count = result

        title = u'New news on Mim\xedr!'
        link = "%s://mimir.ik.nu/news" % (ssl and 'https' or 'http')
        description = 'There '
        if count == 1:
            description += 'is 1 new item'
        else:
            description += 'are %s new items' % count
        description += ' on your news page'

        self.send_notification(entity.full(), True, message_type,
                               title, link, description)
        return user_id

    def _set_notified(self, user_id):
        return self._dbpool.runOperation("""UPDATE news_page SET notified=true
                                            WHERE user_id=%s""", user_id)

    def onEvent(self, message):
        node = message.event.items["node"]

        m = re.match(r"^mimir/news/(.+)$", node)

        if not m:
            return

        channel = m.group(1)

        items = (e for e in message.event.items.elements()
                   if e.name == 'item' and e.news is not None)

        self.process(channel, items)

    def process(self, channel, items):
        d = self._dbpool.runInteraction(self._process_items, channel, items)
        d.addCallback(self.notify)
        d.addErrback(self.error)

    def _process_items(self, cursor, channel, items):

        # Get channel title
        cursor.execute("SELECT title from channels WHERE channel=%s",
                       channel)
        title = cursor.fetchone()[0]

        print "Channel title: %s" % repr(title)

        # Get notify list, including preferences
        cursor.execute("""SELECT user_id, jid, notify,
                                 description_in_notify, message_type,
                                 store_offline, notify_items
                          FROM news_prefs
                            NATURAL JOIN news_subscriptions
                            NATURAL JOIN news_notify
                          WHERE NOT suspended AND channel=%s""",
                       channel)

        notify_list = cursor.fetchall()

        # split notify list into a list of entities that are to be notified
        # and a list of entities that will get items marked as unread
        notifications = []
        mark_unread = []
        for user_id, jid, notify, description_in_notify, message_type, \
            store_offline, notify_items in \
                notify_list:
            if notify and notify_items:
                notifications.append((jid,
                                      description_in_notify,
                                      message_type))
            elif store_offline:
                mark_unread.append(user_id)

        # store items and mark unread
        notify_items = []
        for item in items:
            news_id = self._store_item(cursor, channel, item)
            if news_id:
                for user_id in mark_unread:
                    cursor.execute("""INSERT INTO news_flags
                                      (user_id, news_id, unread) VALUES
                                      (%s, %s, true)""",
                                   (user_id, news_id))
                    cursor.execute("""UPDATE news_page SET notified=false
                                      WHERE user_id=%s""",
                                   user_id)

                notify_items.append(item)
        return (title, notifications, notify_items)

    def _store_item(self, cursor, channel, item):
        title = unicode(item.news.title or '')
        link = unicode(item.news.link or '')
        description = unicode(item.news.description or '')

        print "Storing item: %s" % repr(item.toXml())

        cursor.execute("""UPDATE news
                          SET title=%s, description=%s, date=now()
                          WHERE channel=%s AND link=%s""",
                       (title, description, channel, link))

        if cursor.rowcount == 1:
            print "UPDATE"
            return None

        cursor.execute("""INSERT INTO news
                          (channel, title, link, description) VALUES
                          (%s, %s, %s, %s)""",
                       (channel, title, link, description))

        print "INSERT",

        cursor.execute("""SELECT news_id FROM news
                          WHERE channel=%s and link=%s""",
                          (channel, link))

        news_id = cursor.fetchone()[0]

        print news_id
        return news_id

    def send_notification(self, jid, description_in_notify, message_type,
                          title, link, description):
        
        message = domish.Element(('jabber:client', 'message'))
        message['to'] = jid
        message['type'] = message_type

        if message_type == 'chat':
            body = "%s\n%s" % (title, link)
            if description and description_in_notify:
                body += "\n\n%s\n\n" % description

            message.addElement('body', None, body)
        elif message_type == 'headline':
            message.addElement('subject', None, title)
            if description:
                message.addElement('body', None, description)
            oob = message.addElement(('jabber:x:oob', 'x'))
            oob.addElement('url', None, link)
            oob.addElement('desc', None, title)

        print "Sending: %s" % repr(message.toXml())
        self.xmlstream.send(message)

    def notify(self, result):
        channel_title, notifications, items = result

        for item in items:
            title = "%s: %s" % (channel_title,
                                unicode(item.news.title or '-- no title --'))
            link = unicode(item.news.link or '')
            description = unicode(item.news.description or '') or None
            if description:
                description = SGMLTAG.sub('', description)
                description = domish.unescapeFromXml(description)
                description = description.rstrip() or None

            for jid, description_in_notify, message_type in notifications:
                self.send_notification(jid, description_in_notify, message_type,
                                       title, link, description)
