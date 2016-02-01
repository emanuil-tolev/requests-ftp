from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler, DTPHandler
from pyftpdlib.servers import FTPServer

import socket
import tempfile
import shutil
import threading
import logging

logger = logging.getLogger('pyftpdlib')

class DTPHandlerWithTransferStats(DTPHandler):
    """Class handling server-data-transfer-process (server-DTP, see
    RFC-959) managing data-transfer operations involving sending
    and receiving data. This class additionally returns statistics
    about the transfer that has taken place when sending
    "226 Transfer Complete" to the client. It returns them in a
    multiline 226 response."""

    def handle_close(self):
        """Called when the socket is closed. Override based on pyftpdlib
        v.1.5.0."""
        # If we used channel for receiving we assume that transfer is
        # finished when client closes the connection, if we used channel
        # for sending we have to check that all data has been sent
        # (responding with 226) or not (responding with 426).
        # In both cases handle_close() is automatically called by the
        # underlying asynchat module.
        if not self._closed:
            if self.receive:
                self.transfer_finished = True
            else:
                self.transfer_finished = len(self.producer_fifo) == 0
            try:
                if self.transfer_finished:
                    self._resp = (
                        "226-File successfully transferred\n226 {elapsed_time} seconds"
                            .format(elapsed_time=round(self.get_elapsed_time(), 3)),
                        logger.debug
                    )
                else:
                    tot_bytes = self.get_transmitted_bytes()
                    self._resp = ("426 Transfer aborted; %d bytes transmitted."
                                  % tot_bytes, logger.debug)

                    # log_transfer(
                    # cmd=self.cmd,
                    # filename=self.file_obj.name,
                    # receive=self.receive,
                    # completed=self.transfer_finished,
                    # elapsed=elapsed_time, elapsed_time =
                    # bytes=self.get_transmitted_bytes())
            finally:
                self.close()


class SimpleFTPServer(FTPServer):
    """Starts a simple FTP server on a random free port. """

    ftp_user = property(lambda s: 'fakeusername',
            doc='User name added for authenticated connections')
    ftp_password = property(lambda s: 'qweqwe', doc='Password for ftp_user')

    # Set in __init__
    anon_root = property(lambda s: s._anon_root, doc='Home directory for the anonymous user')
    ftp_home = property(lambda s: s._ftp_home, doc='Home directory for ftp_user')
    ftp_port = property(lambda s: s._ftp_port, doc='TCP port that the server is listening on')

    def __init__(self):
        # Create temp directories for the anonymous and authenticated roots
        self._anon_root = tempfile.mkdtemp()
        self._ftp_home = tempfile.mkdtemp()

        print self._anon_root, self.anon_root
        print self._ftp_home, self.ftp_home
        print self.ftp_user, self.ftp_password

        authorizer = DummyAuthorizer()
        authorizer.add_user(self.ftp_user, self.ftp_password, self.ftp_home, perm='elradfmwM')
        authorizer.add_anonymous(self.anon_root)

        handler = FTPHandler
        handler.authorizer = authorizer

        # Create a socket on any free port
        self._ftp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._ftp_socket.bind(('', 0))
        self._ftp_port = self._ftp_socket.getsockname()[1]
        print self.ftp_port

        # Create a new pyftpdlib server with the socket and handler we've configured
        FTPServer.__init__(self, self._ftp_socket, handler)

    def __del__(self):
        self.close_all()

        if hasattr(self, '_anon_root'):
            shutil.rmtree(self._anon_root, ignore_errors=True)

        if hasattr(self, '_ftp_home'):
            shutil.rmtree(self._ftp_home, ignore_errors=True)


class FTPServerWithTransferStats(FTPServer):
    ftp_user = property(lambda s: 'fakeusername',
            doc='User name added for authenticated connections')
    ftp_password = property(lambda s: 'qweqwe', doc='Password for ftp_user')

    # Set in __init__
    anon_root = property(lambda s: s._anon_root, doc='Home directory for the anonymous user')
    ftp_home = property(lambda s: s._ftp_home, doc='Home directory for ftp_user')
    ftp_port = property(lambda s: s._ftp_port, doc='TCP port that the server is listening on')

    def __init__(self):
        # Create temp directories for the anonymous and authenticated roots
        self._anon_root = tempfile.mkdtemp()
        self._ftp_home = tempfile.mkdtemp()

        print self._anon_root, self.anon_root
        print self._ftp_home, self.ftp_home
        print self.ftp_user, self.ftp_password

        authorizer = DummyAuthorizer()
        authorizer.add_user(self.ftp_user, self.ftp_password, self.ftp_home, perm='elradfmwM')
        authorizer.add_anonymous(self.anon_root)

        handler = FTPHandler
        handler.authorizer = authorizer
        handler.dtp_handler = DTPHandlerWithTransferStats

        # Create a socket on any free port
        self._ftp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._ftp_socket.bind(('', 0))
        self._ftp_port = self._ftp_socket.getsockname()[1]
        print self.ftp_port

        # Create a new pyftpdlib server with the socket and handler we've configured
        FTPServer.__init__(self, self._ftp_socket, handler)

    def __del__(self):
        self.close_all()

        if hasattr(self, '_anon_root'):
            shutil.rmtree(self._anon_root, ignore_errors=True)

        if hasattr(self, '_ftp_home'):
            shutil.rmtree(self._ftp_home, ignore_errors=True)


if __name__ == "__main__":
    server = SimpleFTPServer()
    print("FTPD running on port %d" % server.ftp_port)
    print("Anonymous root: %s" % server.anon_root)
    print("Authenticated root: %s" % server.ftp_home)
    server.serve_forever()
