# TA-iplookupapi

A custom Splunk search command that enriches events with IP geolocation from the
[freeipapi.com](https://freeipapi.com) API (keyless).

## Usage

```
... | iplookupapi <ip_field>
```

For each event, the value of `<ip_field>` is looked up and the geolocation fields
(`countryName`, `countryCode`, `cityName`, `regionName`, `latitude`, `longitude`,
`timeZone`, `zipCode`, …) are merged into the event. A lookup failure sets
`iplookupapi_error` on the event rather than dropping it.

Example:

```
index=firewall | iplookupapi src_ip | stats count by countryName
```

## Compatibility

| Attribute | Value |
|-----------|-------|
| **Python runtime** | 3.13 on Splunk 10.2 and later, 3.9 on Splunk 10.1 and earlier |
| **Expected compatible** | Splunk Enterprise and Cloud 9.3+ and 10.x |
| **Tested in CI** | Real-Splunk harness runs the command end-to-end against a mock upstream + AppInspect `cloud`, `future`, `private_victoria` on every push |
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
