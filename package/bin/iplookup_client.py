"""freeipapi.com lookups for the iplookupapi command (no Splunk imports).

One Lookup object lives for one search. It decides, per field value, whether
to call the upstream at all, remembers every answer so a repeated IP costs one
call, and gives up on the upstream for the rest of the search once it rate
limits or keeps failing. Every outcome is either data to merge or an error
string for the record's iplookupapi_error field; nothing raises.

Upstream behaviour this is built around (checked against the real API, 25 Nov
2026):
  - https://freeipapi.com/api/json/<ip> 307-redirects to
    https://free.freeipapi.com/api/v1/json/<ip>, which is called directly.
  - private, loopback and malformed addresses get HTTP 200 with every field
    null, so they are not sent at all.
  - an empty path looks up the CALLER's address, i.e. the Splunk server's own
    public IP, so an empty value must never reach the URL.
  - the free tier allows 60 requests a minute and answers HTTP 429 beyond it.
"""
import ipaddress

DEFAULT_BASE = "https://free.freeipapi.com"
API_PATH = "/api/v1/json/"
TIMEOUT = 10
MAX_CONSECUTIVE_FAILURES = 3

ERR_INVALID = "invalid IP address"
ERR_NOT_PUBLIC = "not a public IP address"
ERR_MULTIVALUE = "multivalue field: one IP address per event is supported"
ERR_NO_DATA = "freeipapi returned no data for this address"
ERR_BAD_RESPONSE = "freeipapi returned an unexpected response"
ERR_RATE_LIMITED = "rate limited by freeipapi (HTTP 429); later lookups in this search were skipped"


def normalise(value):
    """Return (ip_text, error). (None, None) means: leave the record alone."""
    if value is None:
        return None, None
    if isinstance(value, (list, tuple)):
        values = [v for v in value if str(v).strip()]
        if not values:
            return None, None
        if len(values) > 1:
            return None, ERR_MULTIVALUE
        value = values[0]
    text = str(value).strip()
    if not text:
        return None, None
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None, ERR_INVALID
    if not ip.is_global:
        return None, ERR_NOT_PUBLIC
    return str(ip), None


class Lookup:
    def __init__(self, base=DEFAULT_BASE, get=None, timeout=TIMEOUT,
                 max_failures=MAX_CONSECUTIVE_FAILURES):
        if get is None:
            import requests
            session = requests.Session()
            get = session.get
        self._get = get
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.max_failures = max_failures
        self.cache = {}
        self.calls = 0
        self.failures = 0
        self.stopped = None

    def lookup(self, value):
        """Return (data, error) for one field value; at most one is set."""
        ip, error = normalise(value)
        if error or ip is None:
            return None, error
        if ip in self.cache:
            return self.cache[ip]
        if self.stopped:
            return None, self.stopped
        result = self._call(ip)
        self.cache[ip] = result
        return result

    def _call(self, ip):
        self.calls += 1
        try:
            resp = self._get(self.base + API_PATH + ip, timeout=self.timeout)
        except Exception as exc:  # connection refused, timeout, TLS
            return self._failed("freeipapi request failed: {}".format(type(exc).__name__))
        status = getattr(resp, "status_code", 0)
        if status == 429:
            self.stopped = ERR_RATE_LIMITED
            return None, ERR_RATE_LIMITED
        if status >= 500:
            return self._failed("freeipapi HTTP {}".format(status))
        if status >= 400:
            self.failures = 0
            return None, "freeipapi HTTP {}".format(status)
        try:
            data = resp.json()
        except ValueError:
            return self._failed(ERR_BAD_RESPONSE)
        if not isinstance(data, dict):
            return self._failed(ERR_BAD_RESPONSE)
        self.failures = 0
        if not data.get("ipAddress"):
            return None, ERR_NO_DATA
        return {str(k): v for k, v in data.items()}, None

    def _failed(self, error):
        self.failures += 1
        if self.failures >= self.max_failures:
            self.stopped = ("freeipapi unavailable ({} consecutive failures); "
                            "later lookups in this search were skipped".format(self.failures))
        return None, error
