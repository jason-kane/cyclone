# coding: utf-8

from cyclone.web import _O
from twisted.web import client

class Page(_O):
    pass

class HTTPClientFactory(client.HTTPClientFactory):
    def page(self, page):
        if self.waiting:
            self.waiting = 0
            self.deferred.callback(Page(
                body=page,
                headers=self.response_headers,
                cookies=self.cookies,
            ))

def fetch(url, contextFactory=None, *args, **kwargs):
    def wrapper(error):
        return Page(error=error.getErrorMessage())

    d = client._makeGetterFactory(url, HTTPClientFactory,
        contextFactory=contextFactory, *args, **kwargs).deferred
    d.addErrback(wrapper)
    return d
