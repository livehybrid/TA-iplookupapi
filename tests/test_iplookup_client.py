"""Unit tests for the lookup client (no Splunk needed)."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "package" / "bin"))

import iplookup_client as c  # noqa: E402


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class Upstream:
    def __init__(self, answers=None, default=None):
        self.urls = []
        self.answers = answers or {}
        self.default = default

    def __call__(self, url, timeout):
        self.urls.append(url)
        ip = url.rsplit("/", 1)[1]
        ans = self.answers.get(ip, self.default)
        if isinstance(ans, Exception):
            raise ans
        return ans or Resp(200, {"ipAddress": ip, "countryCode": "XX"})


@pytest.mark.parametrize("value,expected", [
    ("8.8.8.8", ("8.8.8.8", None)),
    (" 8.8.8.8\n", ("8.8.8.8", None)),
    ("2001:4860:4860:0:0:0:0:8888", ("2001:4860:4860::8888", None)),
    (["1.1.1.1"], ("1.1.1.1", None)),
    ("", (None, None)), ("   ", (None, None)), (None, (None, None)), ([], (None, None)),
    ("999.1.1.1", (None, c.ERR_INVALID)), ("notanip", (None, c.ERR_INVALID)),
    ("8.8.8.8/../x", (None, c.ERR_INVALID)),
    ("10.0.0.1", (None, c.ERR_NOT_PUBLIC)), ("::1", (None, c.ERR_NOT_PUBLIC)),
    ("192.168.1.1", (None, c.ERR_NOT_PUBLIC)), ("fe80::1", (None, c.ERR_NOT_PUBLIC)),
    (["1.1.1.1", "8.8.8.8"], (None, c.ERR_MULTIVALUE)),
])
def test_normalise(value, expected):
    assert c.normalise(value) == expected


def test_one_call_per_distinct_ip():
    up = Upstream()
    lk = c.Lookup("http://m", get=up)
    for v in ["8.8.8.8", "8.8.8.8", " 8.8.8.8", "1.1.1.1", "2001:4860:4860::8888", "2001:4860:4860:0::8888"]:
        data, err = lk.lookup(v)
        assert err is None and data["ipAddress"]
    assert sorted(up.urls) == sorted(["http://m/api/v1/json/8.8.8.8", "http://m/api/v1/json/1.1.1.1",
                                      "http://m/api/v1/json/2001:4860:4860::8888"])


def test_invalid_private_and_empty_never_call():
    up = Upstream()
    lk = c.Lookup("http://m", get=up)
    for v in ["", " ", None, "notanip", "10.0.0.1", "::1", ["1.1.1.1", "8.8.8.8"]]:
        assert lk.lookup(v)[0] is None
    assert up.urls == []


def test_429_stops_further_calls():
    up = Upstream({"1.1.1.2": Resp(429, {"message": "Too Many Attempts."})})
    lk = c.Lookup("http://m", get=up)
    assert lk.lookup("1.1.1.1")[1] is None
    assert lk.lookup("1.1.1.2") == (None, c.ERR_RATE_LIMITED)
    assert lk.lookup("1.1.1.3") == (None, c.ERR_RATE_LIMITED)
    assert lk.lookup("1.1.1.1")[1] is None  # already answered: still served from cache
    assert len(up.urls) == 2


def test_4xx_is_per_ip():
    up = Upstream({"1.1.1.2": Resp(404, {})})
    lk = c.Lookup("http://m", get=up)
    assert lk.lookup("1.1.1.2") == (None, "freeipapi HTTP 404")
    assert lk.lookup("1.1.1.3")[1] is None
    assert lk.lookup("1.1.1.2") == (None, "freeipapi HTTP 404")
    assert len(up.urls) == 2


def test_5xx_and_connection_errors_trip_after_three_in_a_row():
    up = Upstream(default=Resp(503, {}))
    up.answers["1.0.0.2"] = ConnectionError("refused")
    lk = c.Lookup("http://m", get=up)
    assert lk.lookup("1.0.0.1") == (None, "freeipapi HTTP 503")
    assert lk.lookup("1.0.0.2")[1].startswith("freeipapi request failed")
    assert lk.lookup("1.0.0.3") == (None, "freeipapi HTTP 503")
    assert "unavailable" in lk.lookup("1.0.0.4")[1]
    assert len(up.urls) == 3


def test_a_success_resets_the_failure_count():
    up = Upstream({"1.0.0.1": Resp(500, {}), "1.0.0.2": Resp(500, {}), "1.0.0.4": Resp(500, {}),
                   "1.0.0.5": Resp(500, {})})
    lk = c.Lookup("http://m", get=up)
    for ip in ["1.0.0.1", "1.0.0.2", "1.0.0.3", "1.0.0.4", "1.0.0.5", "1.0.0.6"]:
        lk.lookup(ip)
    assert lk.stopped is None and len(up.urls) == 6


@pytest.mark.parametrize("resp", [Resp(200, ValueError("not json")), Resp(200, ["x"])])
def test_bad_body(resp):
    lk = c.Lookup("http://m", get=Upstream({"1.1.1.1": resp}))
    assert lk.lookup("1.1.1.1") == (None, c.ERR_BAD_RESPONSE)


def test_all_null_answer_is_not_merged():
    nulls = {"ipAddress": None, "countryName": None, "zipCode": "-"}
    lk = c.Lookup("http://m", get=Upstream({"1.1.1.1": Resp(200, nulls)}))
    assert lk.lookup("1.1.1.1") == (None, c.ERR_NO_DATA)
