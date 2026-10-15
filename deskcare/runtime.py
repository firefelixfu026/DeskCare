"""Runtime guards for a single local DeskCare process."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceGuard(QObject):
    """Keep one DeskCare process per user session.

    A second launch only sends a small ``show`` message to the first process;
    it does not open the database or start another sampler.
    """

    show_requested = Signal()

    def __init__(self, name: str = "DeskCare", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.server: QLocalServer | None = None
        self.primary = False
        probe = QLocalSocket(self)
        probe.connectToServer(self.name)
        if probe.waitForConnected(150):
            probe.write(b"show")
            probe.flush()
            probe.waitForBytesWritten(150)
            probe.disconnectFromServer()
            return

        # A stale endpoint can remain after a crash. Removing it is safe only
        # after the connection probe failed, so an active process is not
        # displaced by a second launch.
        QLocalServer.removeServer(self.name)
        server = QLocalServer(self)
        if not server.listen(self.name):
            return
        self.server = server
        self.primary = True
        server.newConnection.connect(self._accept_connection)

    def _accept_connection(self) -> None:
        if self.server is None:
            return
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            socket.readyRead.connect(lambda socket=socket: self._read_message(socket))
            socket.disconnected.connect(socket.deleteLater)

    def _read_message(self, socket: QLocalSocket) -> None:
        if socket.readAll().data().startswith(b"show"):
            self.show_requested.emit()

