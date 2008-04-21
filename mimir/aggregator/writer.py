# Copyright (c) 2005-2006 Ralph Meijer
# See LICENSE for details

"""
Unparsers for feeds.

Writers create another representation from the Universal Feed Parser's entry
representation.
"""

from twisted.words.xish import domish

NS_XML = 'http://www.w3.org/XML/1998/namespace'
NS_ATOM = 'http://www.w3.org/2005/Atom'

class AtomWriter(object):
    """
    Writer that generates entries that adhere to the Atom specification.
    """

    def generate(self, feed, entry):
        """
        Generate an Atom entry from a feedparser entry.

        @param entry: a parsed feed entry.
        @type entry: L{dict}
        @return: an Atom entry.
        @rtype: L{domish.Element}
        """

        element = domish.Element((NS_ATOM, 'entry'))

        for key, value in entry.iteritems():
            methodname = "_generate_" + key
            try:
                method = getattr(self, methodname)
            except AttributeError:
                continue

            result = method(value)

            if not isinstance(result, list):
                result = [result]

            for item in result:
                element.addChild(item)

        return element

    def generate_person(self, name, data):
        element = domish.Element((None, name))

        for key, value in data.iteritems():
            if key in ['name', 'uri', 'email']:
                element.addElement(key, content=value)

        return element

    def generate_element(self, name, data):
        element = domish.Element((None, name))

        if data:
            element.addContent(data)

        return element

    def generate_text(self, name, data):
        element = domish.Element((None, name))

        if data['value']:
            if data.type == "text/plain":
                element['type'] = 'text'
                element.addContent(domish.escapeToXml(data.value))
            else:
                element['type'] = 'html'
                element.addContent(data.value)

            if 'language' in data and data['language']:
                element[(NS_XML, 'lang')] = data['language']

            if 'base' in data:
                element[(NS_XML, 'base')] = data['base']

        return element

    def _generate_author_detail(self, data):
        return self.generate_person('author', data)

    def _generate_contributor(self, data):
        return [self.generate_person('contributor', item)
                for item in data]

    def _generate_content(self, data):
        elements = []
        for item in data:
            element = self.generate_text('content', item)

            if 'src' in item:
                element['src'] = item['src']

            elements.append(element)

        return elements

    def _generate_feedburner_origlink(self, data):
        element = domish.Element(('http://rssnamespace.org/feedburner/ext/1.0',
                                  'origLink'))
        element.addContent(data)
        return element

    def _generate_id(self, data):
        return self.generate_element('id', data)

    def _generate_links(self, data):
        elements = []
        for item in data:
            element = domish.Element((None, 'link'))
            for key, value in item.iteritems():
                if key in ['rel', 'type', 'href', 'hreflang', 'title', 'length']:
                    element[key] = value

            elements.append(element)

        return elements

    def _generate_published(self, data):
        return self.generate_element('published', data)

    def _generate_subtitle_detail(self, data):
        return self.generate_text('subtitle', data)

    def _generate_summary_detail(self, data):
        return self.generate_text('summary', data)

    def _generate_tags(self, data):
        elements = []

        for item in data:
            element = domish.Element((None, 'category'))
            for key, value in item.iteritems():
                if value and key in ['term', 'scheme', 'label']:
                    element[key] = value

            elements.append(element)

        return elements

    def _generate_title_detail(self, data):
        return self.generate_text('title', data)

    def _generate_updated(self, data):
        return self.generate_element('updated', data)

class MimirWriter(object):
    """
    Writer that generates entries using a custom XML representation.
    """

    def generate(self, feed, entry):
        news = domish.Element(('mimir:news', 'news'))

        if 'title' in entry:
            content = entry.title
            if 'source' in entry and 'title' in entry.source:
                content = "%s: %s" % (entry.source.title, content)
            if entry.title_detail.type == 'text/plain':
                content = domish.escapeToXml(content)
            news.addElement('title', content=content)

        if 'link' in entry:
            url = entry.get('feedburner_origlink', entry.link)

            if url:
                news.addElement('link', content=url)

        # Find a description. First try full text, then summary.
        content = None
        if 'content' in entry:
            content = entry.content[0]
        elif 'summary' in entry:
            content = entry.summary_detail

        if content:
            value = content.value
            if content.type == 'text/plain':
                value = domish.escapeToXml(value)
            news.addElement('description', content=value)

        return news

class StringParser(object):
    """
    Parses a string with serialized XML into a DOM.
    """
    def __init__(self):
        self.elementStream = domish.elementStream()
        self.elementStream.DocumentStartEvent = self.docStart
        self.elementStream.ElementEvent = self.elem
        self.elementStream.DocumentEndEvent = self.docEnd
        self.done = False


    def docStart(self, elem):
        self.document = elem


    def elem(self, elem):
        self.document.addChild(elem)


    def docEnd(self):
        self.done = True


    def parse(self, string):
        self.elementStream.parse(string)
        if not self.done:
            raise Exception("Incomplete XML document input")
        return self.document



class ReconstituteWriter(object):
    """
    Writer that generates Atom entries using Venus' reconsitute module.
    """

    def generate(self, feed, entry):
        from planet.reconstitute import reconstitute

        xdoc = reconstitute(feed, entry)
        xml = xdoc.documentElement.toxml()
        return StringParser().parse(xml.encode('utf-8'))
