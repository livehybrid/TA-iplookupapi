# TA-iplookupapi

A custom Splunk search command that enriches events with IP geolocation from the
[freeipapi.com](https://freeipapi.com) API (keyless).

## Usage

```
... | iplookupapi <ip_field>
```

For each event, the value of `<ip_field>` is looked up and the geolocation fields
(`countryName`, `countryCode`, `cityName`, `regionName`, `latitude`, `longitude`,
`timeZones`, `zipCode`, …) are merged into the event. A lookup failure sets
`iplookupapi_error` on the event rather than dropping it.

## Behaviour

Every event that goes in comes out. The command never fails the search.

| Value in `<ip_field>` | Upstream call | Result |
|---|---|---|
| Public IPv4 or IPv6 address | once per distinct address per search | geolocation fields merged |
| The same address again (any spelling, e.g. `2001:4860:4860:0:0:0:0:8888` and `2001:4860:4860::8888`) | none, answered from the search's cache | the same fields |
| Empty or missing | none | event unchanged |
| Not an IP address | none | `iplookupapi_error="invalid IP address"` |
| Private, loopback, link-local, CGNAT or other non-public address | none | `iplookupapi_error="not a public IP address"` |
| Multivalue | none | `iplookupapi_error="multivalue field: ..."` |
| Upstream answers 4xx or 5xx | for that address only | `iplookupapi_error="freeipapi HTTP <code>"` |
| Upstream answers 200 with no data | for that address only | `iplookupapi_error="freeipapi returned no data ..."` |
| Upstream answers 429 (rate limited) | no further calls in this search | that event and every later one still to be looked up get `iplookupapi_error="rate limited by freeipapi (HTTP 429); ..."` |
| Three upstream failures in a row (5xx, timeout, refused) | no further calls in this search | later events get `iplookupapi_error="freeipapi unavailable ..."` |

Surrounding whitespace is ignored. Empty values are never sent: the upstream
answers an empty lookup with the caller's own address, which would tag the
event with the Splunk server's location. The free tier allows 60 lookups a
minute, so a `dedup` or `stats` before the command keeps large searches inside
it. Lookups go to `https://free.freeipapi.com/api/v1/json/<ip>`, where
`freeipapi.com` now redirects keyless requests.

Example:

```
index=firewall | iplookupapi src_ip | stats count by countryName
```

## Compatibility

| Attribute | Value |
|-----------|-------|
| **Python runtime** | 3.13 on Splunk 10.2 and later, 3.9 on Splunk 10.1 and earlier |
| **Expected compatible** | Splunk Enterprise and Cloud 9.3+ and 10.x |
| **Tested in CI** | Real-Splunk harness (10.0 and 10.6) runs the command end-to-end against a mock upstream (batches with duplicates, IPv6, invalid and private values, 4xx/5xx, 429) + AppInspect `cloud`, `future`, `private_victoria` on every push; a non-gating canary against the real API on main, weekly and on dispatch |
| **Command protocol** | `splunklib.searchcommands` (v2 chunked) |

The command is implemented with `splunklib.searchcommands` (the modern chunked
protocol, replacing the deprecated `splunk.Intersplunk` API). Its dependencies
(`splunklib`, `requests`) are vendored and pinned to versions that stay
3.9-clean.

Splunk 10.2 and later ship Python 3.9 and 3.13 side by side; this add-on sets
`python.required = 3.13`, so it runs on 3.13 there. Splunk 10.1 and earlier
ignore `python.required` and run it on 3.9 (`python.version = python3`), so the
code and vendored libraries stay 3.9-compatible (`requests < 2.33`,
`splunk-sdk < 3`). CI runs the integration tests on Splunk 10.0 (Python 3.9)
and 10.6 (Python 3.13) to hold both.
