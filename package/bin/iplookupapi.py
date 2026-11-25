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

from splunklib.searchcommands import dispatch, StreamingCommand, Configuration

from iplookup_client import DEFAULT_BASE, Lookup


def _resolve_api_base():
    """Base URL for the freeipapi.com API.

    Resolution order (production is unaffected — both overrides are absent in a
    normal install, so it falls through to the real API):
      1. FREEIPAPI_BASE env var (e.g. an enterprise API gateway).
      2. a `local/freeipapi_base` file in the app (the integration harness writes
         this to point the command at a mock upstream — search-command processes
         do not reliably inherit the container env).
      3. the real freeipapi.com API (free.freeipapi.com, where freeipapi.com
         redirects keyless lookups).
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
    return DEFAULT_BASE


FREEIPAPI_BASE = _resolve_api_base()


@Configuration()
class IpLookupApiCommand(StreamingCommand):
    """Merge freeipapi fields into each record; never drop or fail a record.

    One upstream call per distinct public IP per search. Empty values are left
    alone; invalid, private and multivalue values, upstream errors and rate
    limiting set iplookupapi_error instead of geolocation fields.
    """

    def stream(self, records):
        field = self.fieldnames[0] if self.fieldnames else None
        # stream() runs once per chunk of records, in one process per search,
        # so the cache and the rate-limit stop are kept on the command.
        lookup = getattr(self, "_lookup", None)
        if lookup is None:
            lookup = self._lookup = Lookup(FREEIPAPI_BASE)
        for record in records:
            try:
                data, error = lookup.lookup(record.get(field) if field else None)
                if data:
                    record.update(data)
                if error:
                    record["iplookupapi_error"] = error
            except Exception as exc:  # never drop the record on a lookup failure
                record["iplookupapi_error"] = str(exc)
            yield record


if __name__ == "__main__":
    dispatch(IpLookupApiCommand, sys.argv, sys.stdin, sys.stdout, __name__)
