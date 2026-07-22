#!/usr/bin/env python3
"""
Mock freeipapi.com for the integration test — deterministic geolocation for any
IP, so the `iplookupapi` search command can be exercised end-to-end with no real
external call. The command is pointed here via the local/freeipapi_base override
file. Pure stdlib.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re

IP_RE = re.compile(r"^/api/json/([^/?]+)")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        m = IP_RE.match(self.path)
        if m:
            ip = m.group(1)
            body = json.dumps({
                "ipVersion": 4, "ipAddress": ip,
                "latitude": 1.5, "longitude": 2.5,
                "countryName": "MockLand", "countryCode": "MK",
                "regionName": "MockRegion", "cityName": "Mocktown",
                "zipCode": "00000", "timeZone": "+00:00",
                "continent": "Mockcontinent", "continentCode": "MC",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"MOCK {self.command} {self.path}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
