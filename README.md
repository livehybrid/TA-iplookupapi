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
| **Python runtime** | 3.9, Splunk's long-term-support runtime (pinned) |
| **Expected compatible** | Splunk Enterprise and Cloud 9.3+ and 10.x (any release on the Python 3.9 runtime) |
| **Tested in CI** | Real-Splunk harness runs the command end-to-end against a mock upstream + AppInspect `cloud`, `future`, `private_victoria` on every push |
| **Command protocol** | `splunklib.searchcommands` (v2 chunked) |

The command is implemented with `splunklib.searchcommands` (the modern chunked
protocol, replacing the deprecated `splunk.Intersplunk` API). Its dependencies
(`splunklib`, `requests`) are vendored and pinned to versions that stay
3.9-clean. `python.required = 3.9` is set on the command. It is not yet validated
on the opt-in Python 3.13 runtime introduced in Splunk 10.2.
