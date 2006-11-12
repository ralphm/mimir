# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

from twisted.words.protocols.jabber import jid
from twisted.words.xish import domish

from mimir.common import extension

domish.Element.__unicode__ = domish.Element.__str__

class Storage(object):
    def __init__(self, dbpool):
        self._dbpool = dbpool 
        d = self._dbpool.runOperation("""UPDATE presences
                                         SET type='unavailable', show='',
                                             status='', priority=0
                                         WHERE type='available'""")
        def eb(failure):
            print failure
        d.addErrback(eb)

    def set_presence(self, entity, available, show, status, priority):
        return self._dbpool.runInteraction(self._set_presence, entity,
                                                               available,
                                                               show,
                                                               status,
                                                               priority)

    def _set_presence(self, cursor, entity, available, show, status, priority):
        if available:
            type = 'available'
        else:
            type = 'unavailable'

        # changed is True when this resource became the top resource, or when
        # it continued to be the top resource and the availability or show
        # changed, or when another resource became the top resource
        changed = False

        # Find existing entry for this resource
        cursor.execute("""SELECT presence_id, type, show FROM presences
                          WHERE jid=%s AND resource=%s""",
                       (entity.userhost(), entity.resource))
        result = cursor.fetchone()
        print "result: %s" % repr(result)
      
        if result:
            id, old_type, old_show = result

            if old_type == 'unavailable':
                # delete old record, the new record will be inserted below
                cursor.execute("DELETE FROM presences WHERE presence_id=%s",
                               id)
        
        if result and old_type == 'available':
            if show != old_show:
                print "  show != old_show"
                changed = True
            cursor.execute("""UPDATE presences SET
                              type=%s, show=%s, status=%s, priority=%s,
                              last_updated=now()
                              WHERE presence_id=%s""",
                           (type, show, status, priority, id))
        else:
            print "  new presence record"
            changed = True
            cursor.execute("""INSERT INTO presences
                              (type, show, status, priority, jid, resource)
                              VALUES (%s, %s, %s, %s, %s, %s)""",
                           (type, show, status, priority,
                            entity.userhost(), entity.resource))


        return changed

    def update_roster(self, changed, entity):
        return self._dbpool.runInteraction(self._update_roster, changed,
                                                                entity)

    def _update_roster(self, cursor, changed, entity):
        print "Updating roster for %s" % repr(entity.full())

        # Find new top resource's presence id
        cursor.execute("""SELECT presence_id, resource FROM presences
                          WHERE jid=%s ORDER by type, priority desc,
                          (CASE WHEN type='available'
                                THEN presence_id
                                ELSE 0
                           END), last_updated desc""",
                           entity.userhost())
        result = cursor.fetchone()
        top_id, top_resource = result

        # Get old top resource's presence id.
        cursor.execute("SELECT presence_id FROM roster WHERE jid=%s",
                                       entity.userhost())
        result = cursor.fetchone()
        print "result 2: %s" % repr(result)

        if result:
            old_top_id = result[0]
            print "  old_top_id %d" % old_top_id

            if old_top_id != top_id:
                print "  old_top_id != top_id"
                changed = True
            elif entity.resource != top_resource:
                print "  we are not the top resource"
                changed = False
            # else, we are still the top resource. Keep the changed value
            # that got passed.

            cursor.execute("UPDATE roster SET presence_id=%s WHERE jid=%s",
                           (top_id, entity.userhost()))
        else:
            changed = True
            cursor.execute("""INSERT INTO roster
                              (presence_id, jid) VALUES
                              (%s, %s)""",
                           (top_id, entity.userhost()))

        return changed

    def remove_presences(self, entity):
        return self._dbpool.runInteraction(self._remove_presences, entity)

    def _remove_presences(self, cursor, entity):
        cursor.execute("DELETE FROM roster WHERE jid=%s", entity.userhost())
        cursor.execute("DELETE FROM presences WHERE jid=%s", entity.userhost())

class Monitor(extension.ExtensionProtocol):
    def __init__(self, storage):
        self.storage = storage
        self.callbacks = []

    def connectionInitialized(self):
        self.xmlstream.addObserver('/presence', self.on_presence)
        self.send('<presence/>')

    def register_callback(self, f):
        self.callbacks.append(f)

    def store_presence(self, entity, available, show, status, priority):
        d = self.storage.set_presence(entity, available, show, status, priority)
        d.addCallback(self.storage.update_roster, entity)
        def cb(changed, entity):
            print "Changed %s: %s" % (repr(entity.full()), changed)
            if changed:
                for f in self.callbacks:
                    f(entity, available, show)

        d.addCallback(cb, entity)
        d.addErrback(self.error)

    def on_presence(self, presence):
        type = presence.getAttribute("type", None) or 'available'
        try:
            handler = getattr(self, 'on_%s' % (type))
        except AttributeError:
            return
        else:
            handler(presence)

    def on_available(self, presence):
        entity = jid.JID(presence["from"])
        print "Got available presence from %s" % (repr(entity.full()))

        status = unicode(presence.status or '')
        show = unicode(presence.show or '')
        if show not in ['away', 'xa', 'chat', 'dnd']:
            show = ''

        try:
            priority = int(unicode(presence.priority or '')) or 0
        except ValueError:
            priority = 0

        print "  priority %d" % priority

        self.store_presence(entity, True, show, status, priority)

    def on_unavailable(self, presence):
        entity = jid.JID(presence["from"])
        print "Got unavailable presence from %s" % (repr(entity.full()))

        status = unicode(presence.status or '')

        self.store_presence(entity, False, '', status, 0)

    def error(self, failure):
        print failure

class RosterMonitor(Monitor):

    def connectionAuthenticated(self, xs):
        self.send("<iq type='get'><query xmlns='jabber:iq:roster'/></iq>")
        Monitor.connectionAuthenticated(self, xs)

    def on_subscribe(self, presence):
        entity = jid.JID(presence["from"])
        print "Got subscribe presence from %s" % (repr(entity.full()))
        reply = domish.Element(('jabber:client', 'presence'))
        reply['to'] = entity.full()
        reply['type'] = 'subscribed'
        self.send(reply)
       
        # return the favour
        reply['type'] = 'subscribe'
        self.send(reply)
    
    def on_subscribed(self, presence):
        entity = jid.JID(presence["from"])
        print "Got subscribed presence from %s" % (repr(entity.full()))

    def on_unsubscribe(self, presence):
        entity = jid.JID(presence["from"])
        print "Got unsubscribe presence from %s" % (repr(entity.full()))
        reply = domish.Element(('jabber:client', 'presence'))
        reply['to'] = entity.full()
        reply['type'] = 'unsubscribed'
        self.send(reply)
       
        # return the favour
        reply['type'] = 'unsubscribe'
        self.send(reply)

    def on_unsubscribed(self, presence):
        entity = jid.JID(presence["from"])
        print "Got unsubscribed presence from %s" % (repr(entity.full()))
        d = self.storage.remove_presences(entity)
        d.addErrback(self.error)
