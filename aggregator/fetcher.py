from twisted.web import client, error
from twisted.internet import reactor
from twisted.python import failure

import copy

feeds = ['http://test.ralphm.net/blog/atom']

class NotModified(Exception):
    pass

class HTTPFeedGetter(client.HTTPPageGetter):
    """ HTTP page getter for feeds. """

    def handleResponse(self, response):
        # Store the response in cache
        re = self.headers.get("etag", None)
        rl = self.headers.get("last-modified", None)
        rd = self.headers.get("date", None)
        if re or rl or rd:
            cache = {'response': response}
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

    def handleStatus_302(self):
        client.HTTPPageGetter.handleStatus_301(self)

    def handleStatus_303(self):
        self.factory.method = 'GET'
        client.HTTPPageGetter.handleStatus_301(self)

    def handleStatus_304(self):
        """ Handle status 304: Not Modified. """
        # Page was not modified since last time. Find in cache.
        cache_entry = self.factory.cache.get(self.factory.url, None)
        if not cache_entry:
            self.factory.noPage(error.Error(self.status,
                                            self.message,
                                            "Page missing in cache"))
        else:
            self.factory.noPage(NotModified())

class HTTPClientFeedFactory(client.HTTPClientFactory):

    protocol = HTTPFeedGetter
    cache = {}

    def __init__(self, url, method='GET', postdata=None, headers=None,
                 agent="Twisted PageGetter", timeout=0, cookies=None,
                 followRedirect=1):

        self.original_url = copy.copy(url)

        headers = headers or {}

        cached = self.cache.get(url, None)
        if cached:
            etag = cached.get('etag', None)
            last_modified = cached.get('last-modified', None)
            if etag:
                headers.setdefault('if-none-match', etag)
            if last_modified:
                headers.setdefault('if-modified-since', last_modified)

        client.HTTPClientFactory.__init__(self, url=url, method=method,
                postdata=postdata, headers=headers, agent=agent,
                timeout=timeout, cookies=cookies, followRedirect=followRedirect)

    def page(self, page):
        if self.waiting:
            self.waiting = 0
            self.deferred.callback((page, self.original_url))

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
