#!/usr/bin/env python3
"""lsd -- a small LocalSend v2 peer for the ngiangbao.localsend bar widget.

The widget runs this as a child process and talks to it in JSON lines:
commands on stdin, events on stdout. It speaks LocalSend protocol v2
(https://github.com/localsend/protocol): multicast discovery on
224.0.0.167:53317, and an HTTPS server on TCP 53317 for /register,
/prepare-upload, /upload and /cancel.

Visibility works like AirDrop's "Everyone for N minutes": while a receive
window is open this peer answers announcements and accepts uploads; outside
one it stays quiet and refuses them. Scanning (the panel's radar) announces
on its own, so nearby devices answer even when we are not receiving.
"""

import hashlib
import http.client
import http.server
import json
import mimetypes
import os
import re
import secrets
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.parse

PORT = 53317
GROUP = "224.0.0.167"
API = "/api/localsend/v2"
VERSION = "2.1"
PEER_TTL = 30            # seconds a peer stays on the radar without being heard
SCAN_EVERY = 4           # announce period while the radar is open
RECEIVE_ANNOUNCE_EVERY = 10
DECISION_TIMEOUT = 60    # how long a sender waits for Accept / Decline
CHUNK = 256 * 1024

DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                        "ngiangbao-localsend")
CERT = os.path.join(DATA_DIR, "cert.pem")
KEY = os.path.join(DATA_DIR, "key.pem")

_out_lock = threading.Lock()


def emit(ev, **fields):
    fields["ev"] = ev
    line = json.dumps(fields, ensure_ascii=False)
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def log(msg):
    sys.stderr.write("lsd: %s\n" % msg)
    sys.stderr.flush()


def downloads_dir():
    try:
        out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=3)
        path = out.stdout.strip()
        if path and path != os.path.expanduser("~"):
            return path
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.expanduser("~/Downloads")


def ensure_identity():
    """A self-signed certificate; its SHA-256 is our LocalSend fingerprint."""
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    if not (os.path.exists(CERT) and os.path.exists(KEY)):
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
             "-subj", "/CN=LocalSend User", "-keyout", KEY, "-out", CERT],
            check=True, capture_output=True)
        os.chmod(KEY, 0o600)
    der = ssl.PEM_cert_to_DER_cert(open(CERT).read())
    return hashlib.sha256(der).hexdigest().upper()


def ipv4_interfaces():
    """(name, address) for every interface that can carry LAN multicast."""
    try:
        out = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=3)
        data = json.loads(out.stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    skip = re.compile(r"^(lo|docker|br-|veth|tailscale|virbr|tun|wg)")
    result = []
    for link in data:
        name = link.get("ifname", "")
        if skip.match(name) or "UP" not in link.get("flags", []):
            continue
        for a in link.get("addr_info", []):
            if a.get("family") == "inet" and a.get("local"):
                result.append((name, a["local"]))
    return result


def safe_relpath(name):
    """A sender's fileName as a path under the download folder, or None."""
    name = str(name or "").replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    parts = [re.sub(r"[\x00-\x1f]", "", p)[:200] for p in parts]
    if any(not p for p in parts):
        return None
    return os.path.join(*parts)


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists("%s (%d)%s" % (base, n, ext)):
        n += 1
    return "%s (%d)%s" % (base, n, ext)


def notify(title, body):
    try:
        subprocess.Popen(["notify-send", "-a", "LocalSend", "-i", "folder-download", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


STRINGS = {
    "en": {
        "peer_gone": "That device is no longer nearby",
        "nothing_to_send": "Nothing to send",
        "connect_failed": "Couldn't connect: %s",
        "declined": "Declined",
        "busy": "The device is busy",
        "pin": "A PIN is required",
        "error_code": "Error %d",
        "bad_answer": "Invalid response",
        "message_from": "Message from %s",
        "copied": "(copied to the clipboard)",
        "wants_to_send": "%s wants to send files",
        "and_more": " and %d more",
        "received_n": "Received %d file(s)",
        "port_busy": "Port %d is busy (is the LocalSend app open?): %s",
    },
    "vi": {
        "peer_gone": "Thiết bị không còn ở gần",
        "nothing_to_send": "Không có gì để gửi",
        "connect_failed": "Không kết nối được: %s",
        "declined": "Đã bị từ chối",
        "busy": "Thiết bị đang bận",
        "pin": "Cần mã PIN",
        "error_code": "Lỗi %d",
        "bad_answer": "Phản hồi không hợp lệ",
        "message_from": "Tin nhắn từ %s",
        "copied": "(đã chép vào clipboard)",
        "wants_to_send": "%s muốn gửi tệp",
        "and_more": " và %d tệp khác",
        "received_n": "Đã nhận %d tệp",
        "port_busy": "Cổng %d đang bận (app LocalSend đang mở?): %s",
    },
}
LANG = "en"


def tr(key):
    return STRINGS.get(LANG, STRINGS["en"]).get(key) or STRINGS["en"][key]


class Peer:
    def __init__(self, info, ip):
        self.update(info, ip)

    def update(self, info, ip):
        self.fingerprint = str(info.get("fingerprint") or ip)
        self.alias = str(info.get("alias") or ip)[:64]
        self.model = info.get("deviceModel")
        self.type = info.get("deviceType") or "desktop"
        self.ip = ip
        self.port = int(info.get("port") or PORT)
        self.protocol = "http" if info.get("protocol") == "http" else "https"
        self.seen = time.time()

    def public(self):
        return {"fingerprint": self.fingerprint, "alias": self.alias, "deviceModel": self.model,
                "deviceType": self.type, "ip": self.ip}


class Incoming:
    """One /prepare-upload session from a sender."""

    def __init__(self, sender, ip, files):
        self.id = secrets.token_hex(8)
        self.sender = sender
        self.ip = ip
        self.files = files            # id -> metadata dict
        self.tokens = {}
        self.decided = threading.Event()
        self.accepted = False
        self.cancelled = False
        self.total = sum(int(f.get("size") or 0) for f in files.values())
        self.done_bytes = 0
        self.remaining = set()
        self.saved = []


class Node:
    def __init__(self):
        self.fingerprint = ensure_identity()
        self.alias = socket.gethostname()
        self.download_dir = downloads_dir()
        self.auto_accept = False
        self.receive_until = None      # None: not receiving; 0: until turned off
        self.scanning = False
        self.peers = {}
        self.lock = threading.RLock()
        self.session = None
        self.outgoing = {}
        self.server = None
        self.error = ""

    # ---- identity ----------------------------------------------------
    def info(self, announce=None):
        d = {"alias": self.alias, "version": VERSION, "deviceModel": "Linux", "deviceType": "desktop",
             "fingerprint": self.fingerprint, "port": PORT, "protocol": "https", "download": False}
        if announce is not None:
            d["announce"] = announce
        return d

    @property
    def receiving(self):
        u = self.receive_until
        return u is not None and (u == 0 or u > time.time())

    def state(self):
        emit("state", alias=self.alias, fingerprint=self.fingerprint, receiving=self.receiving,
             until=int(self.receive_until or 0) if self.receiving else 0, scanning=self.scanning,
             autoAccept=self.auto_accept, downloadDir=self.download_dir, error=self.error)

    def publish_peers(self):
        with self.lock:
            now = time.time()
            for fp in [fp for fp, p in self.peers.items() if now - p.seen > PEER_TTL]:
                del self.peers[fp]
            peers = [p.public() for p in sorted(self.peers.values(), key=lambda p: p.alias.lower())]
        emit("peers", peers=peers)

    def remember(self, info, ip):
        fp = str(info.get("fingerprint") or "")
        if not fp or fp == self.fingerprint:
            return None
        with self.lock:
            p = self.peers.get(fp)
            new = p is None
            if new:
                p = self.peers[fp] = Peer(info, ip)
            else:
                p.update(info, ip)
        if new:
            self.publish_peers()
        return p

    # ---- multicast ---------------------------------------------------
    def open_multicast(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.bind(("", PORT))
        joined = 0
        for _, addr in ipv4_interfaces():
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                             socket.inet_aton(GROUP) + socket.inet_aton(addr))
                joined += 1
            except OSError:
                pass
        if not joined:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         struct.pack("4s4s", socket.inet_aton(GROUP), socket.inet_aton("0.0.0.0")))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        self.udp = s

    def multicast(self, announce):
        data = json.dumps(self.info(announce)).encode()
        ifaces = ipv4_interfaces() or [("", "0.0.0.0")]
        for _, addr in ifaces:
            try:
                self.udp.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(addr))
                self.udp.sendto(data, (GROUP, PORT))
            except OSError as e:
                log("multicast on %s: %s" % (addr, e))

    def udp_loop(self):
        while True:
            try:
                data, (ip, _) = self.udp.recvfrom(65535)
                msg = json.loads(data.decode("utf-8", "replace"))
            except (OSError, ValueError):
                continue
            if not isinstance(msg, dict):
                continue
            peer = self.remember(msg, ip)
            if peer and msg.get("announce") and self.receiving:
                threading.Thread(target=self.answer, args=(peer,), daemon=True).start()

    def answer(self, peer):
        """Reply to an announcement: HTTP /register first, multicast as fallback."""
        try:
            status, body = self.request(peer, "POST", API + "/register", self.info(), timeout=4)
            if status == 200 and body:
                self.remember(json.loads(body), peer.ip)
            return
        except (OSError, ValueError, http.client.HTTPException):
            pass
        self.multicast(False)

    def tick_loop(self):
        last_receive_announce = 0
        last_scan = 0
        last_publish = 0
        was_receiving = self.receiving
        while True:
            time.sleep(1)
            now = time.time()
            if self.scanning and now - last_scan >= SCAN_EVERY:
                last_scan = now
                self.multicast(True)
            if self.receiving and now - last_receive_announce >= RECEIVE_ANNOUNCE_EVERY:
                last_receive_announce = now
                if not self.scanning:
                    self.multicast(True)
            if was_receiving and not self.receiving:
                self.receive_until = None
                self.state()
            was_receiving = self.receiving
            if now - last_publish >= 3:
                last_publish = now
                self.publish_peers()

    # ---- HTTP client -------------------------------------------------
    def connection(self, peer, timeout):
        if peer.protocol == "https":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return http.client.HTTPSConnection(peer.ip, peer.port, timeout=timeout, context=ctx)
        return http.client.HTTPConnection(peer.ip, peer.port, timeout=timeout)

    def request(self, peer, method, path, payload=None, timeout=10):
        conn = self.connection(peer, timeout)
        try:
            body = json.dumps(payload).encode() if payload is not None else None
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=body, headers=headers)
            r = conn.getresponse()
            return r.status, r.read()
        finally:
            conn.close()

    # ---- sending -----------------------------------------------------
    def send(self, fingerprint, paths):
        with self.lock:
            peer = self.peers.get(fingerprint)
        if not peer:
            emit("transfer", dir="out", status="failed", message=tr("peer_gone"))
            return
        files, local = {}, {}
        for path in paths:
            path = path[7:] if path.startswith("file://") else path
            path = urllib.parse.unquote(path)
            if os.path.isdir(path):
                root = os.path.dirname(os.path.abspath(path))
                for d, _, names in os.walk(path):
                    for n in names:
                        full = os.path.join(d, n)
                        local[full] = os.path.relpath(full, root)
            elif os.path.isfile(path):
                local[path] = os.path.basename(path)
        if not local:
            emit("transfer", dir="out", status="failed", message=tr("nothing_to_send"))
            return
        for full, rel in local.items():
            fid = secrets.token_hex(8)
            files[fid] = {"id": fid, "fileName": rel, "size": os.path.getsize(full),
                          "fileType": mimetypes.guess_type(full)[0] or "application/octet-stream",
                          "_path": full}
        total = sum(f["size"] for f in files.values())
        tid = secrets.token_hex(6)
        job = {"cancel": False, "session": None, "peer": peer}
        self.outgoing[tid] = job
        base = {"id": tid, "dir": "out", "peer": peer.alias, "total": total, "count": len(files)}
        emit("transfer", status="waiting", done=0, **base)
        payload = {"info": self.info(), "files": {k: {x: y for x, y in v.items() if x != "_path"}
                                                   for k, v in files.items()}}
        try:
            status, body = self.request(peer, "POST", API + "/prepare-upload", payload, timeout=DECISION_TIMEOUT + 60)
        except (OSError, http.client.HTTPException) as e:
            emit("transfer", status="failed", done=0, message=tr("connect_failed") % e, **base)
            return
        if job["cancel"]:
            return
        if status == 204:
            emit("transfer", status="done", done=total, **base)
            return
        if status != 200:
            reason = {403: tr("declined"), 409: tr("busy"), 401: tr("pin")}.get(status, tr("error_code") % status)
            emit("transfer", status="declined" if status == 403 else "failed", done=0, message=reason, **base)
            return
        try:
            answer = json.loads(body)
            session, tokens = answer["sessionId"], answer.get("files") or {}
        except (ValueError, KeyError):
            emit("transfer", status="failed", done=0, message=tr("bad_answer"), **base)
            return
        job["session"] = session
        done = 0
        last = 0
        for fid, token in tokens.items():
            meta = files.get(fid)
            if not meta:
                continue
            q = urllib.parse.urlencode({"sessionId": session, "fileId": fid, "token": token})
            conn = self.connection(peer, 60)
            try:
                conn.putrequest("POST", API + "/upload?" + q)
                conn.putheader("Content-Type", "application/octet-stream")
                conn.putheader("Content-Length", str(meta["size"]))
                conn.endheaders()
                with open(meta["_path"], "rb") as fh:
                    while True:
                        if job["cancel"]:
                            raise OSError("cancelled")
                        chunk = fh.read(CHUNK)
                        if not chunk:
                            break
                        conn.send(chunk)
                        done += len(chunk)
                        if time.time() - last > 0.2:
                            last = time.time()
                            emit("transfer", status="transferring", done=done, **base)
                r = conn.getresponse()
                r.read()
                if r.status != 200:
                    raise OSError("receiver answered %d" % r.status)
            except (OSError, http.client.HTTPException) as e:
                if job["cancel"]:
                    emit("transfer", status="cancelled", done=done, **base)
                else:
                    emit("transfer", status="failed", done=done, message=str(e), **base)
                    try:
                        self.request(peer, "POST", API + "/cancel?sessionId=" + urllib.parse.quote(session), timeout=3)
                    except (OSError, http.client.HTTPException):
                        pass
                return
            finally:
                conn.close()
        emit("transfer", status="done", done=total, **base)
        self.outgoing.pop(tid, None)

    def send_text(self, fingerprint, text):
        """A message: one text/plain file whose preview carries the text."""
        with self.lock:
            peer = self.peers.get(fingerprint)
        text = str(text or "")
        if not peer or not text:
            emit("transfer", dir="out", status="failed", message=tr("nothing_to_send"))
            return
        data = text.encode()
        fid = secrets.token_hex(8)
        tid = secrets.token_hex(6)
        base = {"id": tid, "dir": "out", "peer": peer.alias, "total": len(data), "count": 1, "text": True}
        emit("transfer", status="waiting", done=0, **base)
        payload = {"info": self.info(), "files": {fid: {
            "id": fid, "fileName": "message.txt", "size": len(data), "fileType": "text/plain", "preview": text}}}
        try:
            status, body = self.request(peer, "POST", API + "/prepare-upload", payload, timeout=DECISION_TIMEOUT + 60)
        except (OSError, http.client.HTTPException) as e:
            emit("transfer", status="failed", done=0, message=tr("connect_failed") % e, **base)
            return
        if status == 204:
            emit("transfer", status="done", done=len(data), **base)
            return
        if status != 200:
            emit("transfer", status="declined" if status == 403 else "failed", done=0,
                 message=tr("declined") if status == 403 else tr("error_code") % status, **base)
            return
        # The receiver wants the bytes after all.
        try:
            answer = json.loads(body)
            token = answer["files"][fid]
            q = urllib.parse.urlencode({"sessionId": answer["sessionId"], "fileId": fid, "token": token})
            conn = self.connection(peer, 30)
            try:
                conn.request("POST", API + "/upload?" + q, body=data,
                             headers={"Content-Type": "text/plain"})
                r = conn.getresponse()
                r.read()
            finally:
                conn.close()
            ok = r.status == 200
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            ok = False
        emit("transfer", status="done" if ok else "failed", done=len(data) if ok else 0, **base)

    def cancel_outgoing(self, tid):
        job = self.outgoing.get(tid)
        if not job:
            return
        job["cancel"] = True
        if job["session"]:
            try:
                self.request(job["peer"], "POST", API + "/cancel?sessionId=" + urllib.parse.quote(job["session"]), timeout=3)
            except (OSError, http.client.HTTPException):
                pass

    # ---- receiving ---------------------------------------------------
    def set_receiving(self, seconds):
        self.receive_until = 0 if seconds <= 0 else time.time() + seconds
        self.state()
        self.multicast(True)

    def stop_receiving(self):
        self.receive_until = None
        s = self.session
        if s and not s.decided.is_set():
            s.decided.set()
        self.state()

    def decide(self, sid, accept):
        s = self.session
        if s and s.id == sid and not s.decided.is_set():
            s.accepted = bool(accept)
            s.decided.set()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "LocalSend"
    protocol_version = "HTTP/1.1"
    node = None

    def log_message(self, fmt, *args):
        pass

    def reply(self, code, obj=None):
        body = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        if obj is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def read_json(self, limit=4 * 1024 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > limit:
            return None
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return None

    def body_chunks(self):
        """Yield the request body, plain or chunked."""
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    return
                left = size
                while left:
                    b = self.rfile.read(min(left, CHUNK))
                    if not b:
                        raise OSError("truncated")
                    left -= len(b)
                    yield b
                self.rfile.readline()
        else:
            left = int(self.headers.get("Content-Length") or 0)
            while left:
                b = self.rfile.read(min(left, CHUNK))
                if not b:
                    raise OSError("truncated")
                left -= len(b)
                yield b

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in (API + "/info", "/api/localsend/v1/info"):
            info = self.node.info()
            info.pop("port", None)
            info.pop("protocol", None)
            return self.reply(200, info)
        self.reply(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        ip = self.client_address[0]
        node = self.node
        if u.path == API + "/register":
            body = self.read_json()
            if isinstance(body, dict):
                node.remember(body, ip)
            info = node.info()
            return self.reply(200, info)
        if u.path == API + "/prepare-upload":
            return self.prepare(node, ip)
        if u.path == API + "/upload":
            return self.upload(node, ip, q)
        if u.path == API + "/cancel":
            s = node.session
            if s and s.id == q.get("sessionId"):
                s.cancelled = True
                s.decided.set()
                emit("transfer", id=s.id, dir="in", status="cancelled", peer=s.sender.get("alias"),
                     done=s.done_bytes, total=s.total, count=len(s.files))
                node.session = None
            return self.reply(200)
        self.reply(404)

    def prepare(self, node, ip):
        body = self.read_json()
        if not isinstance(body, dict) or not isinstance(body.get("files"), dict) or not isinstance(body.get("info"), dict):
            return self.reply(400, {"message": "Invalid body"})
        if not node.receiving:
            return self.reply(403, {"message": "Not receiving"})
        if node.session is not None:
            return self.reply(409, {"message": "Blocked by another session"})
        sender = body["info"]
        node.remember(sender, ip)
        files = {str(k): v for k, v in body["files"].items() if isinstance(v, dict)}
        if not files:
            return self.reply(400, {"message": "Invalid body"})

        # A message: text sent as a file with the text in its preview.
        if all(str(f.get("fileType", "")).startswith("text/") and f.get("preview") for f in files.values()):
            text = "\n".join(str(f["preview"]) for f in files.values())
            try:
                subprocess.run(["wl-copy"], input=text.encode(), timeout=3)
            except (OSError, subprocess.SubprocessError):
                pass
            emit("message", peer=str(sender.get("alias") or ip), text=text[:2000])
            notify(tr("message_from") % (sender.get("alias") or ip), text[:200] + "\n" + tr("copied"))
            return self.reply(204)

        s = Incoming(sender, ip, files)
        node.session = s
        listing = [{"name": str(f.get("fileName", ""))[:200], "size": int(f.get("size") or 0),
                    "type": str(f.get("fileType", ""))} for f in files.values()]
        if node.auto_accept:
            s.accepted = True
            s.decided.set()
        else:
            emit("request", id=s.id, peer=str(sender.get("alias") or ip),
                 deviceType=sender.get("deviceType") or "", files=listing[:50],
                 count=len(files), total=s.total)
            first = listing[0]["name"] if listing else ""
            more = tr("and_more") % (len(files) - 1) if len(files) > 1 else ""
            notify(tr("wants_to_send") % (sender.get("alias") or ip), first + more)
            s.decided.wait(DECISION_TIMEOUT)
        if not s.accepted or s.cancelled or not node.receiving:
            node.session = None
            emit("transfer", id=s.id, dir="in", status="declined", peer=str(sender.get("alias") or ip),
                 done=0, total=s.total, count=len(files))
            return self.reply(403, {"message": "Rejected"})
        for fid in files:
            s.tokens[fid] = secrets.token_hex(12)
        s.remaining = set(files)
        emit("transfer", id=s.id, dir="in", status="transferring", peer=str(sender.get("alias") or ip),
             done=0, total=s.total, count=len(files))
        self.reply(200, {"sessionId": s.id, "files": s.tokens})

    def upload(self, node, ip, q):
        s = node.session
        fid = q.get("fileId", "")
        if not s or s.id != q.get("sessionId") or s.ip != ip or s.tokens.get(fid) != q.get("token") \
                or fid not in s.remaining:
            return self.reply(403, {"message": "Invalid token or IP address"})
        meta = s.files[fid]
        rel = safe_relpath(meta.get("fileName"))
        if not rel:
            return self.reply(400, {"message": "Invalid file name"})
        dest = unique_path(os.path.join(node.download_dir, rel))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + ".part"
        digest = hashlib.sha256()
        last = 0
        try:
            with open(part, "wb") as fh:
                for chunk in self.body_chunks():
                    if s.cancelled:
                        raise OSError("cancelled")
                    fh.write(chunk)
                    digest.update(chunk)
                    s.done_bytes += len(chunk)
                    if time.time() - last > 0.2:
                        last = time.time()
                        emit("transfer", id=s.id, dir="in", status="transferring",
                             peer=str(s.sender.get("alias") or ip), done=s.done_bytes,
                             total=s.total, count=len(s.files))
        except OSError:
            try:
                os.remove(part)
            except OSError:
                pass
            return self.reply(500, {"message": "Transfer failed"})
        want = meta.get("sha256")
        if want and str(want).lower() != digest.hexdigest():
            os.remove(part)
            return self.reply(422, {"message": "Checksum mismatch"})
        os.replace(part, dest)
        s.remaining.discard(fid)
        s.saved.append(dest)
        emit("received", path=dest, name=os.path.basename(dest), size=os.path.getsize(dest),
             peer=str(s.sender.get("alias") or ip), time=int(time.time()))
        self.reply(200)
        if not s.remaining:
            emit("transfer", id=s.id, dir="in", status="done", peer=str(s.sender.get("alias") or ip),
                 done=s.total, total=s.total, count=len(s.files))
            names = ", ".join(os.path.basename(p) for p in s.saved[:3])
            notify(tr("received_n") % len(s.saved), names)
            node.session = None


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def command_loop(node):
    for line in sys.stdin:
        try:
            c = json.loads(line)
        except ValueError:
            continue
        cmd = c.get("cmd")
        if cmd == "scan":
            node.scanning = bool(c.get("on"))
            if node.scanning:
                node.multicast(True)
            node.state()
        elif cmd == "receive":
            node.set_receiving(int(c.get("seconds") or 0))
        elif cmd == "stop":
            node.stop_receiving()
        elif cmd == "decide":
            node.decide(c.get("id"), c.get("accept"))
        elif cmd == "send":
            threading.Thread(target=node.send, args=(c.get("fingerprint"), list(c.get("paths") or [])),
                             daemon=True).start()
        elif cmd == "sendText":
            threading.Thread(target=node.send_text, args=(c.get("fingerprint"), c.get("text")),
                             daemon=True).start()
        elif cmd == "cancel":
            node.cancel_outgoing(c.get("id"))
        elif cmd == "alias":
            name = str(c.get("name") or "").strip()[:64]
            if name:
                node.alias = name
                node.state()
        elif cmd == "autoAccept":
            node.auto_accept = bool(c.get("on"))
            node.state()
        elif cmd == "lang":
            set_lang(c.get("code"))
        elif cmd == "state":
            node.state()
            node.publish_peers()
    # The widget went away: stop being visible.
    os._exit(0)


def set_lang(code):
    global LANG
    code = str(code or "").lower()
    LANG = "vi" if code.startswith("vi") else "en"


def main():
    set_lang(sys.argv[2] if len(sys.argv) > 2 else os.environ.get("LANG", "en"))
    node = Node()
    if len(sys.argv) > 1 and sys.argv[1]:
        node.alias = sys.argv[1][:64]
    Handler.node = node
    try:
        httpd = Server(("0.0.0.0", PORT), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT, KEY)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True, do_handshake_on_connect=False)
        node.open_multicast()
    except OSError as e:
        node.error = tr("port_busy") % (PORT, e.strerror or e)
        node.state()
        # Keep reading commands so the widget can show the error, but do nothing.
        for _ in sys.stdin:
            node.state()
        return
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=node.udp_loop, daemon=True).start()
    threading.Thread(target=node.tick_loop, daemon=True).start()
    node.state()
    node.publish_peers()
    command_loop(node)


if __name__ == "__main__":
    main()
