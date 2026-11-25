#!/usr/bin/env python3
"""
Mock freeipapi.com for the integration test, so the `iplookupapi` search
command runs end to end with no real external call. The command is pointed here
via the local/freeipapi_base override file. Pure stdlib.

Behaves like the real free endpoint (checked 25 Nov 2026):
  GET /api/v1/json/<ip>  public IP   -> 200, deterministic data derived from the IP
                         other text  -> 200 with every field null (as the real
                                        API does for private and malformed input)
  GET /api/v1/json/      (no IP)     -> 200, the CALLER's address (here
                                        CALLER_IP), as the real API does
Control endpoints for the tests:
  GET  /_mock/requests   every lookup path seen since the last reset
  POST /_mock/reset      clear the log and the scenario
  POST /_mock/scenario   {"status": {"<ip>": 500}, "null": ["<ip>"],
                          "rate_limit_after": N}   N successful lookups, then 429
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import ipaddress
import json
import threading
import urllib.parse

PREFIX = "/api/v1/json/"
CALLER_IP = "192.0.2.200"  # never a valid lookup result: TEST-NET-1
NULL_FIELDS = ["ipVersion", "ipAddress", "latitude", "longitude", "countryName", "countryCode",
               "capital", "cityName", "regionName", "regionCode", "continent", "continentCode",
               "asn", "asnOrganization"]

_LOCK = threading.Lock()
STATE = {"requests": [], "scenario": {}, "served": 0}


def geo(ip):
    """Deterministic data for an IP; tests recompute the same from the IP alone."""
    h = int(hashlib.sha256(ip.encode()).hexdigest(), 16)
    version = ipaddress.ip_address(ip).version
    return {
        "ipVersion": version, "ipAddress": ip,
        "latitude": round((h % 18000) / 100 - 90, 2), "longitude": round((h // 18000 % 36000) / 100 - 180, 2),
        "countryName": "MockLand", "countryCode": "M" + "ABCDEFGHIJ"[h % 10],
        "cityName": "Mocktown-" + str(h % 1000), "regionName": "MockRegion", "regionCode": "MR",
        "zipCode": "00000", "timeZones": ["Etc/UTC", "Mock/Zone"], "phoneCodes": [44],
        "continent": "Mockcontinent", "continentCode": "MC", "isProxy": False,
    }


def nulls():
    d = {k: None for k in NULL_FIELDS}
    d.update({"phoneCodes": [], "timeZones": [], "currencies": [], "languages": [],
              "zipCode": None, "isProxy": False})
    return d


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, status=200, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        with _LOCK:
            if self.path == "/_mock/reset":
                STATE.update(requests=[], scenario={}, served=0)
            elif self.path == "/_mock/scenario":
                STATE["scenario"] = json.loads(raw or b"{}")
                STATE["served"] = 0
            else:
                self._send({"message": "not found"}, 404)
                return
        self._send({"ok": True})

    def do_GET(self):  # noqa: N802
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == "/_mock/requests":
            with _LOCK:
                self._send(list(STATE["requests"]))
            return
        if path == "/_mock/health":
            self._send({"ok": True})
            return
        if not path.startswith(PREFIX):
            self._send({"message": "not found"}, 404)
            return
        ip = path[len(PREFIX):]
        with _LOCK:
            STATE["requests"].append(ip)
            sc = STATE["scenario"]
            limit = sc.get("rate_limit_after")
            if limit is not None and STATE["served"] >= limit:
                self._send({"message": "Too Many Attempts."}, 429, {"Retry-After": "60"})
                return
            status = (sc.get("status") or {}).get(ip)
            if status:
                self._send({"message": "mock error"}, int(status))
                return
            STATE["served"] += 1
            force_null = ip in (sc.get("null") or [])
        if not ip:
            self._send(geo(CALLER_IP))
            return
        try:
            parsed = ipaddress.ip_address(ip)
            public = parsed.is_global and str(parsed) == ip
        except ValueError:
            public = False
        self._send(geo(ip) if public and not force_null else nulls())

    def log_message(self, fmt, *args):
        print(f"MOCK {self.command} {self.path}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
