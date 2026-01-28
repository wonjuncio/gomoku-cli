from __future__ import annotations

import queue
import socket
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

from src.net.protocol import NetMessage, parse_line, to_line, MsgType


class LineSocket:
    """
    Minimal line-based socket wrapper.
    - recv_line(): returns one line without trailing '\\n' or None on disconnect
    - send_line(): sends string (must include '\\n' ideally)
    """
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._buf = b""
        self._send_lock = threading.Lock()

    def send_line(self, line: str) -> None:
        data = line.encode("utf-8")
        with self._send_lock:
            self.sock.sendall(data)

    def recv_line(self) -> Optional[str]:
        while b"\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self._buf += chunk
        raw, self._buf = self._buf.split(b"\n", 1)
        return raw.decode("utf-8", errors="replace")


class Receiver(threading.Thread):
    """
    Dedicated receiver thread:
      - reads lines
      - parses to NetMessage
      - pushes into inbox queue
    """
    def __init__(self, ls: LineSocket, inbox: "queue.Queue[NetMessage]") -> None:
        super().__init__(daemon=True)
        self._ls = ls
        self._inbox = inbox
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        while self._running:
            try:
                line = self._ls.recv_line()
            except Exception:
                line = None

            if line is None:
                # Disconnect notification
                self._inbox.put(NetMessage(MsgType.QUIT, {"msg": "disconnected"}))
                break

            msg = parse_line(line)
            if msg is None:
                continue
            self._inbox.put(msg)


@dataclass
class Transport:
    """
    High-level transport:
      - send(NetMessage)
      - inbox queue for received NetMessage
      - receiver thread
    """
    ls: LineSocket
    inbox: "queue.Queue[NetMessage]"
    receiver: Receiver
    peer: Tuple[str, int]

    def send(self, msg: NetMessage) -> None:
        self.ls.send_line(to_line(msg))

    def close(self) -> None:
        try:
            self.receiver.stop()
        except Exception:
            pass
        try:
            self.ls.sock.close()
        except Exception:
            pass

    # ---------- Factory methods ----------

    @staticmethod
    def connect(host: str, port: int, timeout: float = 10.0) -> "Transport":
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.settimeout(None)

        ls = LineSocket(sock)
        inbox: "queue.Queue[NetMessage]" = queue.Queue()
        peer = (host, port)

        recv = Receiver(ls, inbox)
        recv.start()

        return Transport(ls=ls, inbox=inbox, receiver=recv, peer=peer)

    @staticmethod
    def listen_and_accept(bind_host: str, port: int, backlog: int = 1) -> Tuple["Transport", socket.socket]:
        """
        Returns (Transport, server_socket) so caller can close server socket separately.
        """
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((bind_host, port))
        srv.listen(backlog)

        conn, addr = srv.accept()
        ls = LineSocket(conn)
        inbox: "queue.Queue[NetMessage]" = queue.Queue()
        recv = Receiver(ls, inbox)
        recv.start()

        tr = Transport(ls=ls, inbox=inbox, receiver=recv, peer=(addr[0], addr[1]))
        return tr, srv
