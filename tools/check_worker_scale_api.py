#!/usr/bin/env python3
"""Exercise the locally enabled TypeScript/D1 scale-session slice with dummy data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


def post(base: str, path: str, values: dict[str, str]) -> tuple[int, dict]:
    request = Request(base + path, data=urlencode(values).encode(), method="POST")
    try:
        response = urlopen(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8788")
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        parser.error("This dummy-device test runs only against a local HTTP Worker")
    base = args.url.rstrip("/")

    status, body = post(base, "/once", {"action": "bad"})
    assert (status, body["status"]) == (400, 400)
    status, body = post(base, "/once", {"action": "get"})
    nonce = body["body"]["once"]
    assert status == 200 and re.fullmatch(r"[0-9a-f]{24}", nonce)

    mac = "24:E4:2F:12:34:56"
    form = {"action": "new", "auth": mac, "hashmethod": "sha256",
            "hash": "0" * 64}
    status, body = post(base, "/session", form)
    assert (status, body["status"]) == (403, 403)
    form["hash"] = hashlib.sha256(
        f"{mac}:private-device-secret:{nonce}".encode()
    ).hexdigest()
    status, body = post(base, "/session", form)
    assert status == 200 and body["status"] == 0
    session = body["body"]
    assert re.fullmatch(r"[0-9a-f]{24}", session["sessionid"])
    assert abs(session["syp"]["utc"] - time.time()) < 10
    assert session["ctp"]["goff"] in {3600, 7200}
    assert session["ctp"]["dst"] > time.time()
    assert session["ctp"]["ngoff"] != session["ctp"]["goff"]
    assert session["ind"] == {"stp": 0, "fm": 7, "ws": 0, "tmp": 13, "w": 14}
    roster = session["sp"]["users"]
    assert len(roster) == 1 and roster[0]["id"] == 17
    assert roster[0]["sn"] == "TST" and roster[0]["ht"] == 1.81
    assert roster[0]["cr"] == 123 and roster[0]["sx"] == 0

    status, body = post(base, "/v2/screen", {
        "action": "getbydeviceid", "sessionid": session["sessionid"]})
    assert status == 200 and body == {"status": 0, "body": {"device": [], "user": []}}
    status, body = post(base, "/v2/summary", {
        "action": "getforscale", "sessionid": session["sessionid"]})
    assert status == 200 and body == {"status": 0, "body": []}
    status, body = post(base, "/v2/weather", {
        "action": "getforecast", "sessionid": session["sessionid"]})
    assert (status, body["status"]) == (503, 503)
    event = {"action": "fire", "sessionid": session["sessionid"],
             "type": "1", "epoch": "1792560000", "data": '{"kind":"test"}'}
    for _ in range(2):
        status, body = post(base, "/v2/event", event)
        assert status == 200 and body == {"status": 0}

    measure = {"action": "batchstore", "sessionid": session["sessionid"],
               "macaddress": mac, "userid": "17", "devtype": "1", "category": "1",
               "attribstatus": "0", "measuregrps": json.dumps({"measuregrps": [
                   {"meastime": 1792560000, "measures": [
                       {"value": 73250, "type": 1, "unit": -3}]}]})}
    for _ in range(2):
        status, body = post(base, "/measure", measure)
        assert status == 200 and body == {"status": 0}
    invalid = measure | {"measuregrps": '{"measuregrps":[]}'}
    status, body = post(base, "/measure", invalid)
    assert (status, body["status"]) == (400, 400)

    status, body = post(base, "/session", form)
    assert (status, body["status"]) == (403, 403), "challenge replay was accepted"
    for _ in range(2):
        status, body = post(base, "/session", {
            "action": "delete", "sessionid": session["sessionid"]})
        assert status == 200 and body == {"status": 0}
    status, body = post(base, "/v2/screen", {
        "action": "getbydeviceid", "sessionid": session["sessionid"]})
    assert (status, body["status"]) == (403, 403)
    status, fresh = post(base, "/once", {"action": "get"})
    assert status == 200
    form["hash"] = hashlib.sha256(
        f"{mac}:private-device-secret:{fresh['body']['once']}".encode()
    ).hexdigest()
    status, second = post(base, "/session", form)
    assert status == 200 and "sp" not in second["body"], "one-shot roster repeated"
    status, closed = post(base, "/session", {
        "action": "delete", "sessionid": second["body"]["sessionid"]})
    assert status == 200 and closed == {"status": 0}
    # WS-30 uses the captured v101 request shape, with entirely synthetic data.
    mac = "00:11:22:33:44:66"
    status, challenge = post(base, "/once", {"action": "get"})
    assert status == 200
    form = {"action": "new", "auth": mac, "mfgid": "262153", "currentfw": "101",
            "batterylvl": "63", "duration": "300", "zreboot": "1", "trigger": "weather", "enrich": "t",
            "hash": hashlib.md5(f"{mac}:0123456789abcdef:{challenge['body']['once']}".encode()).hexdigest()}
    status, body = post(base, "/session", form)
    assert status == 200, body
    session = body["body"]
    assert set(session) == {"sessionid", "syp", "ctp"}
    assert abs(session["syp"]["utc"] - time.time()) < 10
    assert session["ctp"]["goff"] in {3600, 7200}
    status, body = post(base, "/v2/summary", {"action": "getforscale", "sessionid": session["sessionid"]})
    assert status == 200 and body == {"status": 0, "body": []}
    measure = {"action": "batchstore", "sessionid": session["sessionid"], "macaddress": mac,
               "userid": "17", "devtype": "1", "category": "1", "attribstatus": "0",
               "measuregrps": json.dumps({"measuregrps": [{"meastime": int(time.time()),
                   "measures": [{"value": 73250, "type": 1, "unit": -3}]}]})}
    for _ in range(2):
        status, body = post(base, "/measure", measure)
        assert status == 200 and body["status"] == 0
        assert body["body"][0]["measuregrps"] == []
        assert abs(body["body"][0]["updatetime"] - time.time()) < 10
    status, _ = post(base, "/session", form)
    assert status == 403, "WS-30 challenge replay was accepted"
    status, body = post(base, "/session", {"action": "delete", "sessionid": session["sessionid"]})
    assert status == 200 and body == {"status": 0}
    status, _ = post(base, "/measure", measure)
    assert status == 403, "WS-30 closed session was accepted"
    print("Local scale API check passed: WBS06 + WS-30 auth, replay, clock, fixtures, durable measure retry, close")


if __name__ == "__main__":
    main()
