#!/usr/bin/env python
"""
iplookupapi custom search command.

Enriches events with IP geolocation from the freeipapi.com API:

    ... | iplookupapi <ip_field>

Rewritten from the deprecated splunk.Intersplunk API to
splunklib.searchcommands (the v2 "chunked" protocol) so it runs on the vendored,
3.9-pinned libraries.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, "lib"))

import requests
from splunklib.searchcommands import dispatch, StreamingCommand, Configuration


def _resolve_api_base():
    """Base URL for the freeipapi.com API.

    Resolution order (production is unaffected — both overrides are absent in a
    normal install, so it falls through to the real API):
      1. FREEIPAPI_BASE env var (e.g. an enterprise API gateway).
      2. a `local/freeipapi_base` file in the app (the integration harness writes
         this to point the command at a mock upstream — search-command processes
         do not reliably inherit the container env).
      3. the real freeipapi.com API.
    """
    env = os.environ.get("FREEIPAPI_BASE")
    if env:
        return env.rstrip("/")
    override = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "local", "freeipapi_base")
    try:
        with open(override) as fh:
            val = fh.read().strip()
        if val:
            return val.rstrip("/")
    except OSError:
        pass
    return "https://freeipapi.com"


FREEIPAPI_BASE = _resolve_api_base()


def get_ip_location(ip):
    resp = requests.get(f"{FREEIPAPI_BASE}/api/json/{ip}", timeout=30, verify=True)
    resp.raise_for_status()
    return resp.json()


@Configuration()
class IpLookupApiCommand(StreamingCommand):
    def stream(self, records):
        field = self.fieldnames[0] if self.fieldnames else None
        for record in records:
            try:
                value = record.get(field) if field else None
                if value:
                    data = get_ip_location(value)
                    if isinstance(data, dict):
                        record.update({str(k): v for k, v in data.items()})
            except Exception as exc:  # never drop the record on a lookup failure
                record["iplookupapi_error"] = str(exc)
            yield record


if __name__ == "__main__":
    dispatch(IpLookupApiCommand, sys.argv, sys.stdin, sys.stdout, __name__)
