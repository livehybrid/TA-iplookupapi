"""
Real-API canary: the command against the real free freeipapi endpoint.

Non-gating (its own CI job; publish does not depend on it). It catches upstream
drift a mock cannot: a moved endpoint (freeipapi.com already redirects keyless
lookups to free.freeipapi.com), renamed fields, a changed answer for private
addresses. Structure only, and two lookups, well inside the 60 a minute free
limit.
"""
from __future__ import annotations

import os
import re
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IPLOOKUP_LIVE_CANARY", "") != "1",
    reason="IPLOOKUP_LIVE_CANARY!=1: real-API canary skipped",
)


def _run(splunk, spl):
    results = []
    for _ in range(12):  # the command may take a moment to register after install
        results = splunk.search(spl, earliest="-5m", count=50)
        if results and all(r.get("countryCode") or r.get("iplookupapi_error") for r in results):
            break
        time.sleep(5)
    return results


def test_real_lookup_structure(splunk):
    spl = ('| makeresults format=csv data="n,ip\n1,8.8.8.8\n2,2001:4860:4860::8888\n3,10.0.0.1" '
           '| iplookupapi ip | table n ip iplookupapi_error ipVersion ipAddress countryCode countryName '
           'latitude longitude timeZones')
    rows = {r["n"]: r for r in _run(splunk, spl)}
    assert sorted(rows) == ["1", "2", "3"], f"events lost: {sorted(rows)}"
    for n, version, ip in (("1", "4", "8.8.8.8"), ("2", "6", "2001:4860:4860::8888")):
        row = rows[n]
        assert not row.get("iplookupapi_error"), f"real lookup failed: {row.get('iplookupapi_error')}"
        assert row.get("ipAddress") == ip and row.get("ipVersion") == version, row
        assert re.fullmatch(r"[A-Z]{2}", row.get("countryCode") or ""), row
        assert row.get("countryName"), row
        assert -90 <= float(row["latitude"]) <= 90 and -180 <= float(row["longitude"]) <= 180, row
    assert rows["3"].get("iplookupapi_error") == "not a public IP address", rows["3"]
    assert not rows["3"].get("countryCode"), rows["3"]
