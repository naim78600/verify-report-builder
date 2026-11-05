"""A tiny local SMTP server for tests (Python 3.12 has no smtpd).  Nothing leaves the machine."""
from __future__ import annotations

import base64
import socketserver
import threading


class _Handler(socketserver.StreamRequestHandler):
    def _send(self, line: str):
        self.wfile.write((line + "\r\n").encode())
        self.wfile.flush()

    def handle(self):
        srv = self.server
        self._send("220 fake.local ESMTP ready")
        mail_from, rcpts = None, []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            cmd = line.upper()
            if cmd.startswith("EHLO") or cmd.startswith("HELO"):
                self.wfile.write(b"250-fake.local\r\n250-AUTH PLAIN LOGIN\r\n250 8BITMIME\r\n")
                self.wfile.flush()
            elif cmd.startswith("AUTH PLAIN"):
                parts = line.split(" ", 2)
                blob = parts[2] if len(parts) > 2 else ""
                try:
                    _, user, pw = base64.b64decode(blob).decode().split("\x00")
                except Exception:
                    self._send("501 bad auth")
                    continue
                if srv.password is not None and pw != srv.password:
                    self._send("535 5.7.8 Authentication failed")
                else:
                    srv.logins.append(user)
                    self._send("235 2.7.0 Authentication successful")
            elif cmd.startswith("MAIL FROM"):
                mail_from = line[10:].strip().strip("<>").split(">")[0]
                rcpts = []
                self._send("250 OK")
            elif cmd.startswith("RCPT TO"):
                addr = line[8:].strip().strip("<>").split(">")[0]
                if addr in srv.refuse:
                    self._send("550 no such user")
                else:
                    rcpts.append(addr)
                    self._send("250 OK")
            elif cmd == "DATA":
                self._send("354 End data with <CR><LF>.<CR><LF>")
                chunks = []
                while True:
                    ln = self.rfile.readline()
                    if ln in (b".\r\n", b""):
                        break
                    chunks.append(ln[1:] if ln.startswith(b"..") else ln)
                srv.messages.append({"from": mail_from, "to": list(rcpts), "data": b"".join(chunks)})
                self._send("250 OK queued")
            elif cmd == "RSET":
                self._send("250 OK")
            elif cmd == "NOOP":
                self._send("250 OK")
            elif cmd == "QUIT":
                self._send("221 Bye")
                return
            else:
                self._send("502 not implemented")


class FakeSMTP(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, password: str | None = None, refuse=()):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.password, self.refuse = password, set(refuse)
        self.messages, self.logins = [], []
        self._t = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.server_address[1]

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self.shutdown()
        self.server_close()
