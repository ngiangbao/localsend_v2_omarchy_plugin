#!/usr/bin/env python3
"""Interop test: bin/lsd.py against the upstream LocalSend CLI.

    LOCALSEND_CLI=/path/to/localsend-cli python3 tests/interop.py

Checks, on 127.0.0.1:
  1. upstream -> lsd: files and a folder arrive intact, with their sha256 and
     modification times (protocol 2.2 checksums, 2.1 metadata);
  2. upstream -> lsd: a text message arrives as a message;
  3. lsd -> upstream: a file arrives intact at the upstream receiver;
  4. lsd as receiver answers a checksum mismatch with 422, allows a retry,
     and ends the session after the last allowed attempt.

The upstream CLI sends to an IP on port 53317, so lsd must own that port:
close the LocalSend app (and the widget) first. Exit status 0 means pass.
"""

import hashlib
import http.client
import json
import os
import pty
import queue
import secrets
import select
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LSD = os.path.join(ROOT, "bin", "lsd.py")
CLI = os.environ.get("LOCALSEND_CLI") or shutil.which("localsend-cli")
API = "/api/localsend/v2"
CLI_PORT = 53318
FAILURES = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILURES.append(what)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


class Lsd:
    def __init__(self, tmp):
        self.events = queue.Queue()
        self.downloads = os.path.join(tmp, "lsd-in")
        env = dict(os.environ, LSD_DOWNLOAD_DIR=self.downloads, LSD_DATA_DIR=os.path.join(tmp, "lsd-data"))
        self.proc = subprocess.Popen([sys.executable, "-u", LSD, "lsd-test", "en"], env=env, text=True,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.proc.stdout:
            try:
                self.events.put(json.loads(line))
            except ValueError:
                pass

    def cmd(self, **c):
        self.proc.stdin.write(json.dumps(c) + "\n")
        self.proc.stdin.flush()

    def wait(self, pred, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                e = self.events.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                break
            if pred(e):
                return e
        return None

    def drain(self):
        while not self.events.empty():
            self.events.get_nowait()


def cli_env(tmp):
    return dict(os.environ, XDG_CONFIG_HOME=os.path.join(tmp, "cli-config"), HOME=os.path.join(tmp, "cli-home"),
                LOCALSEND_ALIAS="upstream-cli", LOCALSEND_PORT=str(CLI_PORT),
                LOCALSEND_DESTINATION=os.path.join(tmp, "cli-in"))


def upstream_sends_files(lsd, tmp):
    src = os.path.join(tmp, "src")
    os.makedirs(os.path.join(src, "folder", "sub"))
    files = {"one.bin": os.urandom(300 * 1024 + 7), "folder/a.txt": b"hello\n",
             "folder/sub/b.bin": os.urandom(2 * 1024 * 1024)}
    for rel, data in files.items():
        with open(os.path.join(src, rel), "wb") as fh:
            fh.write(data)
    old = time.time() - 86400 * 30
    os.utime(os.path.join(src, "one.bin"), (old, old))

    lsd.drain()
    r = subprocess.run([CLI, "send", "--to", "127.0.0.1", os.path.join(src, "one.bin"), os.path.join(src, "folder")],
                       env=cli_env(tmp), capture_output=True, text=True, timeout=120)
    check(r.returncode == 0, "upstream CLI sends files to lsd (exit %d) %s" % (r.returncode, r.stderr.strip()[-300:]))
    done = lsd.wait(lambda e: e.get("ev") == "transfer" and e.get("dir") == "in"
                    and e.get("status") in ("done", "failed", "declined", "cancelled"))
    check(done is not None and done["status"] == "done", "lsd reports the incoming transfer done: %s" % done)
    for rel, data in files.items():
        got = os.path.join(lsd.downloads, rel)
        check(os.path.isfile(got) and sha(got) == hashlib.sha256(data).hexdigest(), "received %s intact" % rel)
    got = os.path.join(lsd.downloads, "one.bin")
    check(os.path.isfile(got) and abs(os.path.getmtime(got) - old) < 2, "modification time kept from metadata")


def upstream_sends_text(lsd, tmp):
    lsd.drain()
    r = subprocess.run([CLI, "send", "--to", "127.0.0.1", "--text", "xin chào 👋"],
                       env=cli_env(tmp), capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, "upstream CLI sends a text message (exit %d) %s" % (r.returncode, r.stderr.strip()[-300:]))
    msg = lsd.wait(lambda e: e.get("ev") == "message", timeout=10)
    check(msg is not None and msg.get("text") == "xin chào 👋", "lsd receives the message: %s" % msg)


def lsd_sends_to_upstream(lsd, tmp):
    """The CLI's interactive receiver runs in a pty; we press Y for it."""
    peers = lsd.wait(lambda e: e.get("ev") == "peers" and any(p["alias"] == "upstream-cli" for p in e["peers"]),
                     timeout=10)
    lsd.cmd(cmd="state")
    peers = peers or lsd.wait(lambda e: e.get("ev") == "peers"
                              and any(p["alias"] == "upstream-cli" for p in e["peers"]), timeout=10)
    check(peers is not None, "lsd knows the upstream device")
    if not peers:
        return
    fp = [p for p in peers["peers"] if p["alias"] == "upstream-cli"][0]["fingerprint"]

    os.makedirs(os.path.join(tmp, "cli-in"), exist_ok=True)
    master, slave = pty.openpty()
    env = cli_env(tmp)
    env.update(TERM="xterm", COLUMNS="120", LINES="40")
    proc = subprocess.Popen([CLI], env=env, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    out = b""

    def pump(seconds, until=None):
        nonlocal out
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([master], [], [], 0.2)
            if r:
                try:
                    out += os.read(master, 65536)
                except OSError:
                    return False
                if until and until in out:
                    return True
        return False

    try:
        pump(4)  # let the server come up
        payload = os.urandom(512 * 1024)
        path = os.path.join(tmp, "to-upstream.bin")
        with open(path, "wb") as fh:
            fh.write(payload)
        lsd.drain()
        lsd.cmd(cmd="send", fingerprint=fp, paths=[path])
        asked = pump(20, b"Accept?")
        check(asked, "upstream receiver is asked to accept")
        os.write(master, b"y")
        end = lsd.wait(lambda e: e.get("ev") == "transfer" and e.get("dir") == "out"
                       and e.get("status") in ("done", "failed", "declined", "cancelled"))
        check(end is not None and end["status"] == "done", "lsd reports the outgoing transfer done: %s" % end)
        got = os.path.join(tmp, "cli-in", "to-upstream.bin")
        for _ in range(20):
            if os.path.isfile(got):
                break
            time.sleep(0.25)
        check(os.path.isfile(got) and sha(got) == hashlib.sha256(payload).hexdigest(),
              "upstream received the file intact (sha256 checked by upstream)")
        if not os.path.isfile(got):
            pump(1)
            print(out.decode("utf-8", "replace")[-2000:])
            for d, _, names in os.walk(tmp):
                print(d, names)
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        os.close(master)


def lsd_checksum_retry(lsd):
    """Raw protocol: a wrong body gets 422 twice, then the right one passes;
    then a file that never matches ends the session after three tries."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def post(path, body, json_body=True):
        c = http.client.HTTPSConnection("127.0.0.1", 53317, context=ctx, timeout=20)
        data = json.dumps(body).encode() if json_body else body
        c.request("POST", path, body=data, headers={"Content-Type": "application/json"})
        r = c.getresponse()
        res = r.status, r.read()
        c.close()
        return res

    info = {"alias": "raw", "version": "2.2", "deviceModel": "test", "deviceType": "headless",
            "fingerprint": secrets.token_hex(16), "port": 9, "protocol": "https", "download": False}
    for name, fixed in (("retry-ok.bin", True), ("retry-bad.bin", False)):
        good = os.urandom(4096)
        fid = "f1"
        st, body = post(API + "/prepare-upload", {"info": info, "files": {fid: {
            "id": fid, "fileName": name, "size": len(good), "fileType": "application/octet-stream",
            "sha256": hashlib.sha256(good).hexdigest()}}})
        check(st == 200, "raw prepare-upload accepted (%d)" % st)
        if st != 200:
            return
        ans = json.loads(body)
        q = "%s/upload?sessionId=%s&fileId=%s&token=%s" % (API, ans["sessionId"], fid, ans["files"][fid])
        bad = bytes(4096)
        codes = [post(q, bad, False)[0], post(q, bad, False)[0], post(q, good if fixed else bad, False)[0]]
        if fixed:
            check(codes == [422, 422, 200], "checksum mismatch -> 422, retry succeeds: %s" % codes)
        else:
            check(codes == [422, 422, 422], "three mismatches -> 422 each: %s" % codes)
            st, _ = post(q, good, False)
            check(st == 403, "no fourth attempt; session ended (%d)" % st)
            check(not os.path.exists(os.path.join(lsd.downloads, name)), "mismatched file not saved")


def main():
    if not CLI or not os.access(CLI, os.X_OK):
        print("Set LOCALSEND_CLI to the upstream localsend-cli binary", file=sys.stderr)
        return 2
    tmp = tempfile.mkdtemp(prefix="lsd-interop-")
    lsd = Lsd(tmp)
    try:
        state = lsd.wait(lambda e: e.get("ev") == "state")
        check(state is not None and not state.get("error"), "lsd starts: %s" % state)
        if not state or state.get("error"):
            return 1
        lsd.cmd(cmd="autoAccept", on=True)
        lsd.cmd(cmd="receive", seconds=0)
        lsd.wait(lambda e: e.get("ev") == "state" and e.get("receiving"))
        upstream_sends_files(lsd, tmp)
        upstream_sends_text(lsd, tmp)
        lsd_checksum_retry(lsd)
        lsd_sends_to_upstream(lsd, tmp)
    finally:
        lsd.proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d failure(s)" % len(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
