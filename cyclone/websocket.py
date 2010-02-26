#!/usr/bin/env python
#
# Copyright 2009 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import functools
from collections import deque

from twisted.python import log
from twisted.protocols.basic import LineReceiver
import cyclone.escape
import cyclone.web


class WebsocketsServerProtocol(LineReceiver):
    """
    Websockets protocol 
    
    Based on  http://bitbucket.org/rushman/tx-websockets/src/tip/websockets.py
    Stripped down all handshake facilities as it happens somewhere outside 
    """

    def __init__(self):
        self.__buffer = ''
        
    def connectionMade(self):
        self.__buffer = ''
        self._messages = deque() #non cunsumed messages stored here
        self._wait_message_cb = None #consumer callback waiting for message, only one at a time
    
    def connectionLost(self, reason):
        pass
    
    def rawDataReceived(self, data):
        """Override this for when raw data is received.
        """
        self.__buffer += data
        while self.__buffer:
            frame_type = ord(self.__buffer[0])
            if frame_type < 0x80:
                frame_end = self.__buffer.index('\xff', 1)
                if frame_end == -1:
                    return
                self.onMessage(self.__buffer[1:frame_end])
                self.__buffer = self.__buffer[frame_end+1:]
            else:
                raise NotImplementedError('unsupported frame type')
            
    def onMessage(self, data):
        if self._wait_message_cb:
            self._wait_message_cb(data)
            self._wait_message_cb = None
        else:
            #Nobody waits for message, save it for future consumption
            self._messages.append(data)

    def wait_message(self,callback):
        if self._messages:
            callback(self._messages.popleft())
        else:
            self._wait_message_cb = callback
        
    def sendMessage(self, message):
        if isinstance(message, dict):
            message = cyclone.escape.json_encode(message)
        if isinstance(message, unicode):
            message = message.encode("utf-8")
        assert isinstance(message, str)
        self.transport.write('\0%s\xff' % message)

class WebSocketHandler(cyclone.web.RequestHandler):
    """A request handler for HTML 5 Web Sockets.

    See http://www.w3.org/TR/2009/WD-websockets-20091222/ for details on the
    JavaScript interface. We implement the protocol as specified at
    http://tools.ietf.org/html/draft-hixie-thewebsocketprotocol-55.

    Here is an example Web Socket handler that echos back all received messages
    back to the client:

      class EchoWebSocket(websocket.WebSocketHandler):
          def open(self):
              self.receive_message(self.on_message)

          def on_message(self, message):
             self.write_message(u"You said: " + message)

    Web Sockets are not standard HTTP connections. The "handshake" is HTTP,
    but after the handshake, the protocol is message-based. Consequently,
    most of the Tornado HTTP facilities are not available in handlers of this
    type. The only communication methods available to you are send_message()
    and receive_message(). Likewise, your request handler class should
    implement open() method rather than get() or post().

    If you map the handler above to "/websocket" in your application, you can
    invoke it in JavaScript with:

      var ws = new WebSocket("ws://localhost:8888/websocket");
      ws.onopen = function() {
         ws.send("Hello, world");
      };
      ws.onmessage = function (evt) {
         alert(evt.data);
      };

    This script pops up an alert box that says "You said: Hello, world".
    """
    def _execute(self, transforms, *args, **kwargs):
        if self.request.headers.get("Upgrade") != "WebSocket" or \
           self.request.headers.get("Connection") != "Upgrade" or \
           not self.request.headers.get("Origin"):
            message = "Expected WebSocket headers"
            self.request.connection.write(
                "HTTP/1.1 403 Forbidden\r\nContent-Length: " +
                str(len(message)) + "\r\n\r\n" + message)
            return

        #otherwise replace protocol with new one
        old_proto = self.request.connection #cyclone.httpserver.HTTPConnection
        
        wsproto = WebsocketsServerProtocol()
        wsproto.factory = old_proto.factory #cyclone.web.Application
        wsproto.transport = old_proto.transport #twisted.internet.tcp.Server
        wsproto.transport.protocol = wsproto
        wsproto.connectionMade()
        wsproto.setRawMode()

        self.request.connection = wsproto
        self.stream = wsproto.transport

        self.stream.write(
            "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
            "Upgrade: WebSocket\r\n"
            "Connection: Upgrade\r\n"
            "Server: TornadoServer/0.1\r\n"
            "WebSocket-Origin: " + self.request.headers["Origin"] + "\r\n"
            "WebSocket-Location: ws://" + self.request.host +
            self.request.path + "\r\n\r\n")

        wsproto.setRawMode()
        self.async_callback(self.open)(*args, **kwargs)
    
    def receive_message(self, callback):
        """Calls callback when the browser calls send() on this Web Socket."""
        callback = self.async_callback(callback)
        self.request.connection.wait_message(callback)
    
    def async_callback(self, callback, *args, **kwargs):
        """Wrap callbacks with this if they are used on asynchronous requests.

        Catches exceptions properly and closes this Web Socket if an exception
        is uncaught.
        """
        if args or kwargs:
            callback = functools.partial(callback, *args, **kwargs)
        def wrapper(*args, **kwargs):
            try:
                return callback(*args, **kwargs)
            except Exception, e:
                log.err("Uncaught exception in %s :: %s" %
                              (self.request.path, str(e)))
                self.stream.loseConnection()
        return wrapper

    def open(self):
        """
        Called on handshake
        """

    def write_message(self, message):
        """
        Call it to write message
        """
        self.request.connection.sendMessage(message)

    def _not_supported(self, *args, **kwargs):
        raise Exception("Method not supported for Web Sockets")

for method in ["write", "redirect", "set_header", "send_error", "set_cookie",
               "set_status", "flush", "finish"]:
    setattr(WebSocketHandler, method, WebSocketHandler._not_supported)
