#!/usr/bin/env python3
"""Compare upstream LocalSend with what this plugin was last tested against.

    python3 tools/check_upstream.py            # print a JSON report
    python3 tools/check_upstream.py --pinned   # report the pinned versions only (no network)
    python3 tools/check_upstream.py --write    # record the latest upstream in upstream.json

Upstream is two repositories: the app (localsend/localsend, latest release and
the protocol version it speaks) and the protocol spec (localsend/protocol).
With GITHUB_OUTPUT set, the report is also written there for the workflow.
GH_TOKEN / GITHUB_TOKEN is used for the GitHub API when present.
"""

import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "upstream.json")
LSD = os.path.join(ROOT, "bin", "lsd.py")
APP = "localsend/localsend"
SPEC = "localsend/protocol"
CONSTANTS = "packages/localsend_isolates/lib/constants.dart"


def get(url, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": "ngiangbao-localsend-upstream-check"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    return body if raw else json.loads(body)


def our_protocol():
    m = re.search(r'^VERSION = "([0-9.]+)"', open(LSD).read(), re.M)
    return m.group(1)


def latest():
    tag = get("https://api.github.com/repos/%s/releases/latest" % APP)["tag_name"]
    constants = get("https://raw.githubusercontent.com/%s/%s/%s" % (APP, tag, CONSTANTS), raw=True)
    m = re.search(r"protocolVersion\s*=\s*'([0-9.]+)'", constants)
    spec = get("https://api.github.com/repos/%s/commits/HEAD" % SPEC)
    readme = get("https://raw.githubusercontent.com/%s/%s/README.md" % (SPEC, spec["sha"]), raw=True)
    s = re.search(r"Protocol v([0-9.]+)", readme)
    return {"appTag": tag, "appProtocol": m.group(1) if m else None,
            "specCommit": spec["sha"], "specVersion": s.group(1) if s else None}


def major(v):
    return str(v or "").split(".")[0]


def minor_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0")))


def main():
    pinned = json.load(open(STATE))
    ours = our_protocol()
    if "--pinned" in sys.argv:
        report = dict(pinned, changed=False, needsReview=False, ourProtocol=ours, notes=[])
    else:
        now = latest()
        notes = []
        for key, version in (("appProtocol", now["appProtocol"]), ("specVersion", now["specVersion"])):
            if version and minor_tuple(version) > minor_tuple(ours):
                notes.append("%s %s is newer than the %s this plugin speaks" % (key, version, ours))
            if version and major(version) != major(ours):
                notes.append("%s %s is a new major protocol version" % (key, version))
        if now["appProtocol"] is None:
            notes.append("could not read protocolVersion from %s at %s" % (CONSTANTS, now["appTag"]))
        changed = any(now[k] != pinned.get(k) for k in now)
        report = dict(now, changed=changed, needsReview=bool(notes), ourProtocol=ours, notes=notes,
                      previous={k: pinned.get(k) for k in now})
        if "--write" in sys.argv and changed:
            pinned.update(now)
            with open(STATE, "w") as fh:
                json.dump(pinned, fh, indent=2)
                fh.write("\n")
    print(json.dumps(report, indent=2))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write("tag=%s\n" % report["appTag"])
            fh.write("changed=%s\n" % str(report["changed"]).lower())
            fh.write("needs_review=%s\n" % str(report["needsReview"]).lower())
            fh.write("report<<EOF\n%s\nEOF\n" % json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
