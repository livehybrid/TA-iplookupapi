"""
Live behaviour tests: the custom search command runs and enriches events.

The docker harness runs a mock freeipapi (docker/mock) and points the command at
it via the app-local override file, so this needs no real external call. The
mock is driven through /_mock/scenario and every lookup it receives is read
back from /_mock/requests, a route the command never consults. Expected
geolocation is recomputed per IP with the mock's own formula, so a row that
received another row's data fails.

Documented behaviour under test (README "Behaviour"):
  - one upstream call per distinct public IP per search, IPv4 and IPv6;
  - empty or missing values are left alone, with no call;
  - invalid, private and multivalue values set iplookupapi_error, with no call;
  - upstream 4xx/5xx set iplookupapi_error on that event only;
  - HTTP 429 stops further calls for the rest of the search, and the events
    still to be looked up get iplookupapi_error;
  - every input event comes out, and no event carries another IP's data.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import time
import urllib.parse
import urllib.request

import pytest

_mgmt_host = urllib.parse.urlparse(
    os.environ.get("SPLUNK_MGMT_URL", "https://127.0.0.1:8089")
).hostname or "127.0.0.1"
pytestmark = pytest.mark.skipif(
    _mgmt_host not in ("127.0.0.1", "localhost", "::1"),
    reason="mock upstream runs on the test runner; a remote Splunk cannot reach it",
)

MOCK = os.environ.get("FREEIPAPI_MOCK_URL", "http://127.0.0.1:8080")
_spec = importlib.util.spec_from_file_location(
    "mock_freeipapi", pathlib.Path(__file__).resolve().parents[1] / "docker" / "mock" / "mock_freeipapi.py")
mock_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock_mod)

ERR_INVALID = "invalid IP address"
ERR_NOT_PUBLIC = "not a public IP address"
ERR_RATE = "rate limited by freeipapi (HTTP 429)"
GEO_FIELDS = ("countryName", "countryCode", "cityName", "latitude", "ipAddress", "ipVersion")


def _mock_post(path, body=None):
    req = urllib.request.Request(MOCK + path, data=json.dumps(body or {}).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def _mock_requests():
    with urllib.request.urlopen(MOCK + "/_mock/requests", timeout=10) as r:
        return json.load(r)


@pytest.fixture
def mock():
    _mock_post("/_mock/reset")
    yield _mock_post
    _mock_post("/_mock/reset")


def _csv_search(splunk, rows, tail=""):
    """Run rows (n, ip) through the command; return results keyed by n."""
    data = "n,ip\n" + "\n".join(f"{n},{ip}" for n, ip in rows)
    spl = f'| makeresults format=csv data="{data}" {tail}| iplookupapi ip | table n ip iplookupapi_error ' + \
        " ".join(GEO_FIELDS)
    results = splunk.search(spl, earliest="-5m", count=1000)
    return {r["n"]: r for r in results}


def _assert_enriched(row, ip):
    want = mock_mod.geo(ip)
    got = {k: row.get(k) for k in ("ipAddress", "cityName", "countryCode")}
    assert got == {"ipAddress": ip, "cityName": want["cityName"], "countryCode": want["countryCode"]}, \
        f"row {row.get('n')} ({row.get('ip')!r}) carries the wrong data: {row}"
    assert not row.get("iplookupapi_error"), f"row {row.get('n')} errored: {row}"


def _assert_not_enriched(row):
    present = [k for k in GEO_FIELDS if row.get(k) not in (None, "")]
    assert not present, f"row {row.get('n')} ({row.get('ip')!r}) gained {present}: {row}"


def test_iplookupapi_command_enriches(splunk, mock):
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
    assert row.get("cityName") == mock_mod.geo("8.8.8.8")["cityName"], f"unexpected payload: {row}"


def test_many_ips_with_duplicates_one_call_each(splunk, mock):
    rows = [(1, "8.8.8.8"), (2, "1.1.1.1"), (3, "8.8.8.8"), (4, "2001:4860:4860::8888"),
            (5, "9.9.9.9"), (6, "2001:4860:4860:0:0:0:0:8888"), (7, "8.8.8.8"), (8, "1.1.1.1"),
            (9, "208.67.222.222"), (10, "9.9.9.9")]
    canonical = {"2001:4860:4860:0:0:0:0:8888": "2001:4860:4860::8888"}
    out = _csv_search(splunk, rows)
    assert sorted(out, key=int) == [str(n) for n, _ in rows], f"events lost: {sorted(out)}"
    for n, ip in rows:
        _assert_enriched(out[str(n)], canonical.get(ip, ip))
    calls = _mock_requests()
    distinct = {canonical.get(ip, ip) for _, ip in rows}
    assert sorted(calls) == sorted(distinct), (
        f"{len(calls)} upstream calls for {len(distinct)} distinct IPs: {sorted(calls)}")


def test_ipv6(splunk, mock):
    out = _csv_search(splunk, [(1, "2606:4700:4700::1111"), (2, "2a00:1450:4009:81f::200e")])
    for n, ip in ((1, "2606:4700:4700::1111"), (2, "2a00:1450:4009:81f::200e")):
        _assert_enriched(out[str(n)], ip)
        assert out[str(n)].get("ipVersion") == "6", out[str(n)]


def test_invalid_private_and_empty_values_are_not_looked_up(splunk, mock):
    rows = [(1, "999.1.1.1"), (2, "notanip"), (3, "10.0.0.1"), (4, "::1"), (5, ""),
            (6, "192.168.1.20"), (7, "8.8.8.8/../x"), (8, "fe80::1"), (9, "100.64.0.1")]
    # Row 10 has no ip field at all; row 11 is multivalue.
    tail = ('| append [| makeresults | eval n=10] '
            '| append [| makeresults | eval n=11, ip=split("1.1.1.1;8.8.8.8", ";")] ')
    out = _csv_search(splunk, rows, tail=tail)
    assert sorted(out, key=int) == [str(n) for n in range(1, 12)], f"events lost: {sorted(out)}"
    expected = {1: ERR_INVALID, 2: ERR_INVALID, 3: ERR_NOT_PUBLIC, 4: ERR_NOT_PUBLIC, 5: None,
                6: ERR_NOT_PUBLIC, 7: ERR_INVALID, 8: ERR_NOT_PUBLIC, 9: ERR_NOT_PUBLIC, 10: None,
                11: "multivalue"}
    for n, err in expected.items():
        row = out[str(n)]
        _assert_not_enriched(row)
        got = row.get("iplookupapi_error")
        if err is None:
            assert not got, f"row {n} should be left alone: {row}"
        else:
            assert got and err in got, f"row {n}: expected {err!r}, got {got!r}"
    calls = _mock_requests()
    assert calls == [], f"the upstream was called for values that must not be sent: {calls}"


def test_upstream_errors_are_per_event_and_do_not_kill_the_search(splunk, mock):
    mock("/_mock/scenario", {"status": {"1.0.0.1": 500, "1.0.0.2": 404, "1.0.0.3": 503}})
    rows = [(1, "1.0.0.1"), (2, "8.8.8.8"), (3, "1.0.0.2"), (4, "1.0.0.3"), (5, "1.1.1.1"), (6, "1.0.0.1")]
    out = _csv_search(splunk, rows)
    assert sorted(out, key=int) == [str(n) for n, _ in rows], f"events lost: {sorted(out)}"
    _assert_enriched(out["2"], "8.8.8.8")
    _assert_enriched(out["5"], "1.1.1.1")
    for n, code in ((1, 500), (3, 404), (4, 503), (6, 500)):
        _assert_not_enriched(out[str(n)])
        assert out[str(n)].get("iplookupapi_error") == f"freeipapi HTTP {code}", out[str(n)]
    assert sorted(_mock_requests()) == sorted(["1.0.0.1", "8.8.8.8", "1.0.0.2", "1.0.0.3", "1.1.1.1"])


def test_empty_answer_is_not_merged(splunk, mock):
    mock("/_mock/scenario", {"null": ["8.8.4.4"]})
    out = _csv_search(splunk, [(1, "8.8.4.4"), (2, "8.8.8.8")])
    _assert_not_enriched(out["1"])
    assert "no data" in (out["1"].get("iplookupapi_error") or ""), out["1"]
    _assert_enriched(out["2"], "8.8.8.8")


def test_rate_limit_stops_calls_and_marks_the_rest(splunk, mock):
    mock("/_mock/scenario", {"rate_limit_after": 2})
    rows = [(1, "1.1.1.1"), (2, "8.8.8.8"), (3, "9.9.9.9"), (4, "1.1.1.1"), (5, "208.67.222.222"),
            (6, "8.8.4.4"), (7, "8.8.8.8")]
    out = _csv_search(splunk, rows)
    assert sorted(out, key=int) == [str(n) for n, _ in rows], f"events lost: {sorted(out)}"
    for n in (1, 2, 4, 7):  # answered before the limit, or repeats of those
        _assert_enriched(out[str(n)], dict(rows)[n])
    for n in (3, 5, 6):
        _assert_not_enriched(out[str(n)])
        assert ERR_RATE in (out[str(n)].get("iplookupapi_error") or ""), out[str(n)]
    calls = _mock_requests()
    assert calls == ["1.1.1.1", "8.8.8.8", "9.9.9.9"], f"calls after the 429: {calls}"
