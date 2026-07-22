"""
Live behaviour test — the custom search command runs and enriches events.

The docker harness runs a mock freeipapi (docker/mock) and points the command at
it via the app-local override file. This proves the command dispatches on the
Splunk 10 / Python 3.9 runtime, imports the vendored splunklib + requests, calls
the upstream and merges the response into the event — with no real external call.
"""
from __future__ import annotations

import time


def test_iplookupapi_command_enriches(splunk):
    spl = '| makeresults | eval ip="8.8.8.8" | iplookupapi ip'
    results = []
    for _ in range(18):  # command may take a moment to register after install
        results = splunk.search(spl, earliest="-5m")
        if results and (results[0].get("countryName") or results[0].get("iplookupapi_error")):
            break
        time.sleep(5)
    assert results, "iplookupapi command returned no results"
    row = results[0]
    assert not row.get("iplookupapi_error"), f"command errored: {row.get('iplookupapi_error')}"
    assert row.get("countryName") == "MockLand", f"command did not enrich the event: {row}"
    assert row.get("cityName") == "Mocktown", f"unexpected enrichment payload: {row}"
