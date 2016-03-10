#!/usr/bin/env python

"""
Dummy server used for unit testing.
"""
from __future__ import print_function

import logging
import sys
import threading
import socket
import warnings


log = logging.getLogger(__name__)


def consume_socket(sock, chunks=65536):
    while not sock.recv(chunks).endswith(b'\r\n'):
        pass


def _has_ipv6(host):
    """ Returns True if the system can bind an IPv6 address. """
    sock = None
    has_ipv6 = False

    if socket.has_ipv6:
        # has_ipv6 returns true if cPython was compiled with IPv6 support.
        # It does not tell us if the system has IPv6 support enabled. To
        # determine that we must bind to an IPv6 address.
        # https://github.com/shazow/urllib3/pull/611
        # https://bugs.python.org/issue658327
        try:
            sock = socket.socket(socket.AF_INET6)
            sock.bind((host, 0))
            has_ipv6 = True
        except:
            pass

    if sock:
        sock.close()
    return has_ipv6

# Some systems may have IPv6 support but DNS may not be configured
# properly. We can not count that localhost will resolve to ::1 on all
# systems. See https://github.com/shazow/urllib3/pull/611 and
# https://bugs.python.org/issue18792
HAS_IPV6_AND_DNS = _has_ipv6('localhost')
HAS_IPV6 = _has_ipv6('::1')


# Different types of servers we have:

class FTPWarning(Warning):
    pass


class NoIPv6Warning(FTPWarning):
    "IPv6 is not available"
    pass


class SocketServerThread(threading.Thread):
    """
    :param socket_handler: Callable which receives a socket argument for one
        request.
    :param ready_event: Event which gets set when the socket handler is
        ready to receive requests.
    """
    USE_IPV6 = HAS_IPV6_AND_DNS

    def __init__(self, socket_handler, host='localhost', port=8081,
                 ready_event=None):
        threading.Thread.__init__(self)
        self.daemon = True

        self.socket_handler = socket_handler
        self.host = host
        self.ready_event = ready_event

    def _start_server(self):
        if self.USE_IPV6:
            sock = socket.socket(socket.AF_INET6)
        else:
            warnings.warn("No IPv6 support. Falling back to IPv4.",
                          NoIPv6Warning)
            sock = socket.socket(socket.AF_INET)
        if sys.platform != 'win32':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, 0))
        self.port = sock.getsockname()[1]

        # Once listen() returns, the server socket is ready
        sock.listen(0)

        if self.ready_event:
            self.ready_event.set()

        self._handle_socket(sock)

    def _handle_socket(self, sock):
        self.socket_handler(sock)
        sock.close()

    def run(self):
        self._start_server()


class DelayedSocketServerThread(SocketServerThread):
    def __init__(self, *args, **kwargs):
        SocketServerThread.__init__(self, *args, **kwargs)
        self.socks = []  # sockets that need closing later

    def _handle_socket(self, sock):
        # we expect that the socket handler passed in will return a list
        # of sockets which need cleaning up later
        self.socks = self.socket_handler(sock)


class SocketDummyServer(object):
    """
    A simple socket-based server is created for this class that is good for
    exactly one request.
    """
    host = 'localhost'
    server_thread = None
    socks = []
    port = None
    server_thread_class = SocketServerThread

    @classmethod
    def _start_server(cls, socket_handler):
        ready_event = threading.Event()
        cls.server_thread = cls.server_thread_class(
            socket_handler=socket_handler,
            ready_event=ready_event,
            host=cls.host
        )
        cls.server_thread.start()
        ready_event.wait(5)
        if not ready_event.is_set():
            raise Exception("most likely failed to start server")
        cls.port = cls.server_thread.port

    @classmethod
    def start_response_handler(cls, response, num=1, block_send=None):
        ready_event = threading.Event()

        def socket_handler(listener):
            socks = []
            for _ in range(num):
                ready_event.set()

                sock = listener.accept()[0]
                consume_socket(sock)
                if block_send:
                    block_send.wait()
                    block_send.clear()
                sock.send(response)
                socks.append(sock)

            return socks

        cls._start_server(socket_handler)
        return ready_event


class DelayedCloseSocketDummyServer(SocketDummyServer):
    server_thread_class = DelayedSocketServerThread

    @classmethod
    def _start_server(cls, socket_handler):
        super(DelayedCloseSocketDummyServer, cls)._start_server(socket_handler)
        cls.socks = cls.server_thread.socks

    @classmethod
    def start_response_handler(cls, response, num=1, block_send=None):
        ready_event = threading.Event()

        def socket_handler(listener):
            socks = []
            for _ in range(num):
                ready_event.set()

                sock = listener.accept()[0]
                consume_socket(sock)
                if block_send:
                    block_send.wait()
                    block_send.clear()
                sock.send(response)
                socks.append(sock)

            return socks

        cls._start_server(socket_handler)
        return ready_event

    @classmethod
    def cleanup(cls):
        for sock in cls.socks:
            sock.close()


class IPV4SocketDummyServer(SocketDummyServer):
    @classmethod
    def _start_server(cls, socket_handler):
        ready_event = threading.Event()
        cls.server_thread = SocketServerThread(socket_handler=socket_handler,
                                               ready_event=ready_event,
                                               host=cls.host)
        cls.server_thread.USE_IPV6 = False
        cls.server_thread.start()
        ready_event.wait(5)
        if not ready_event.is_set():
            raise Exception("most likely failed to start server")
        cls.port = cls.server_thread.port


class FTPSocketDummyServer(DelayedCloseSocketDummyServer):
    @classmethod
    def start_response_handler(
            cls, response, num=1, block_send=None,
            welcome_first=b'220 Welcome to ftpdummy 0.1\r\n',
            user_resp=b'230 Login successful.\r\n',
            type_i_resp=b'200 Switching to Binary mode.\r\n',
            pasv_resp=b'227 Entering Passive Mode (127,0,0,1,?,?).\r\n'  # TODO fill in ? for port #
    ):
        ready_event = threading.Event()

        def socket_handler(listener):
            # Python's ftplib expects and does various things when initiating a connection:
            # 1. it consumes a welcome message
            # 2. it sends "USER anonymous" if no auth provided
            # 3. it sends "TYPE I", switching to binary mode
            # 4. it sends "PASV", requesting details for a data conn
            # 5. it opens a connection to the host and port provided
            # by PASV.
            # 6. [not gotten to this one yet] it most probably finally
            # sends RETR via the control channel, causing data transfer
            # on the data connection.
            # We handle the expected sequence of steps 1-4. Step 5 would
            # require another thread serving DummyServer for the data
            # connection.
            socks = []
            for _ in range(num):
                ready_event.set()

                sock = listener.accept()[0]
                if welcome_first:
                    sock.send(welcome_first)
                consume_socket(sock)
                if user_resp:
                    sock.send(user_resp)
                consume_socket(sock)
                if type_i_resp:
                    sock.send(type_i_resp)
                consume_socket(sock)
                if pasv_resp:
                    sock.send(pasv_resp)
                # TODO respond to data connection open
                if block_send:
                    block_send.wait()
                    block_send.clear()
                sock.send(response)
                socks.append(sock)

            return socks

        cls._start_server(socket_handler)
        return ready_event


if __name__ == '__main__':
    def welcome_handler(listener):
        sock = listener.accept()[0]

        sock.send(b'220 Welcome to ftpdummy 0.1\r\n')
        sock.close()

    # SocketDummyServer stores various bits of data in class attributes
    # so we create a copy of the class to serve another socket at the
    # same time as SocketDummyServer itself. Don't use this in tests -
    # for benchmarking tests and similar tests, use the real FTP server
    # provided in tests.simple_ftpd by pyftpdlib.
    CopyOfSocketDummyServer = type('CopyOfSocketDummyServer',
                                   SocketDummyServer.__bases__,
                                   dict(SocketDummyServer.__dict__))

    SocketDummyServer._start_server(welcome_handler)
    CopyOfSocketDummyServer.start_response_handler(b'226 Transfer Complete.\r\n')
    FTPSocketDummyServer.start_response_handler(b'226 Transfer Complete.\r\n')
    server_threads = [SocketDummyServer.server_thread,
                      CopyOfSocketDummyServer.server_thread,
                      FTPSocketDummyServer.server_thread]
    print("Welcome message server (1 req only) listening on {0}:{1}".format(
        SocketDummyServer.host, SocketDummyServer.port))
    print("RETR successful response server (1 req only) listening on {0}:{1}".format(
        CopyOfSocketDummyServer.host, CopyOfSocketDummyServer.port))
    print("RETR successful response server (with FTP handshake) "
          "listening on {0}:{1}"
          .format(FTPSocketDummyServer.host, FTPSocketDummyServer.port))
    print("Send SIGTERM (kill) to this python proccess to stop serving "
          "immediately.")
    for t in server_threads:
        t.join()
    print('All servers have finished. Stopping.')