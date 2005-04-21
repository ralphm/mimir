from twisted.web import client, error
from twisted.internet import reactor
from twisted.python import failure
import feedparser
import copy

feeds = ['http://test.ralphm.net/blog/atom']

class NotModified(Exception):
    pass

class Headers(object):
    def __init__(self, headers):
        self.dict = dict([(k, v[0]) for k, v in headers.iteritems()])
        self.get = self.dict.get

    def getheader(self, header):
        return self.get(header.lower(), None)

class FeedResource(object):
    def __init__(self, data, url, status, headers):
        self.data = data
        self.url = url
        self.status = status
        self.headers = Headers(headers)

    def info(self):
        return self.headers

    def read(self):
        return self.data

class HTTPFeedGetter(client.HTTPPageGetter):
    """ HTTP page getter for feeds. """

    def handleResponse(self, response):
        # Store the response in cache
        re = self.headers.get("etag", None)
        rl = self.headers.get("last-modified", None)
        rd = self.headers.get("date", None)
        if re or rl or rd:
            cache = {}
            if re:
                cache['etag'] = re[-1]
            if rl and rd:
                cache['last-modified'] = rl[-1]
            elif rd and not rl:
                cache['last-modified'] = rd[-1]

            self.factory.cache[self.factory.original_url] = cache
       
        # Act like a normal HTTPPageGetter
        client.HTTPPageGetter.handleResponse(self, response)

    def handleStatus_301(self):
        """ Handle status 301: Moved Permanently. """
        client.HTTPPageGetter.handleStatus_301(self)
        self.factory.original_url = self.factory.url
        self.factory.real_status = self.status

    def handleStatus_302(self):
        client.HTTPPageGetter.handleStatus_301(self)
        self.factory.real_status = self.status

    def handleStatus_303(self):
        self.factory.method = 'GET'
        client.HTTPPageGetter.handleStatus_301(self)
        self.factory.real_status = self.status

    def handleStatus_304(self):
        """ Handle status 304: Not Modified. """
        self.factory.noPage(NotModified())

class HTTPClientFeedFactory(client.HTTPClientFactory):

    protocol = HTTPFeedGetter
    cache = {}

    def __init__(self, url, method='GET', postdata=None, headers=None,
                 agent="Twisted PageGetter", timeout=0, cookies=None,
                 followRedirect=1):

        self.original_url = copy.copy(url)
        self.real_status = None

        headers = headers or {}

        cached = self.cache.get(url, None)
        if cached:
            etag = cached.get('etag', None)
            last_modified = cached.get('last-modified', None)
            if etag:
                headers.setdefault('if-none-match', etag)
            if last_modified:
                headers.setdefault('if-modified-since', last_modified)

        headers.setdefault('accept-encoding', 'gzip, deflate')
        headers.setdefault('accept', feedparser.ACCEPT_HEADER)

        client.HTTPClientFactory.__init__(self, url=url, method=method,
                postdata=postdata, headers=headers, agent=agent,
                timeout=timeout, cookies=cookies, followRedirect=followRedirect)

    def page(self, page):
        if self.waiting:
            self.waiting = 0
            resource = FeedResource(page, self.url,
                                    self.real_status or self.status,
                                    self.response_headers)
            d = feedparser.parse(resource)
            self.deferred.callback(d)

def getFeed(url, contextFactory=None, *args, **kwargs):
    """ Download a web page as a string, keep a cache of already downloaded
        pages.

    Download a page. Return a deferred, which will callback with a
    page (as a string) or errback with a description of the error.

    See HTTPClientCacheFactory to see what extra args can be passed.
    """
    scheme, host, port, path = client._parse(url)
    factory = HTTPClientFeedFactory(url, *args, **kwargs)
    if scheme == 'https':
        from twisted.internet import ssl
        if contextFactory is None:
            contextFactory = ssl.ClientContextFactory()
        reactor.connectSSL(host, port, factory, contextFactory)
    else:
        reactor.connectTCP(host, port, factory)
    return factory.deferred
