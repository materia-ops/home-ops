#!/usr/bin/env python3
"""Prometheus exporter for the UniFi OS console's disk health (Storage page).

unpoller can't see this: the Network API only lists the console's internal
partitions. UniFi OS returns the bay disks under `ustorage` in /api/system,
and only to a logged-in session; API keys are refused there.
"""
import http.cookiejar
import http.server
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = os.environ.get("UNIFI_URL", "https://192.168.1.1").rstrip("/")
USERNAME = os.environ["UNIFI_USERNAME"]
PASSWORD = os.environ["UNIFI_PASSWORD"]
PORT = int(os.environ.get("LISTEN_PORT", "8080"))
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "60"))
# Worst case per collect is three requests, which must fit the 30s scrape timeout.
REQUEST_TIMEOUT = 8
LOGIN_BACKOFF_MAX = 1800

# The console serves a self-signed certificate.
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=_ctx),
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
)
_csrf = ""
_cache = (0.0, "")
_cache_lock = threading.Lock()
_login_failures = 0
_next_login_at = 0.0


def log(msg):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


def _request(path, body=None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if _csrf:
        headers["X-CSRF-Token"] = _csrf
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    return _opener.open(req, timeout=REQUEST_TIMEOUT)


def login():
    # Back off after failures so a rotated password can't trip the console's
    # login rate limiting with a failed attempt every minute.
    global _csrf, _login_failures, _next_login_at
    if time.monotonic() < _next_login_at:
        raise RuntimeError(f"login backoff after {_login_failures} failure(s)")
    try:
        with _request("/api/auth/login", {"username": USERNAME, "password": PASSWORD, "rememberMe": False}) as resp:
            _csrf = resp.headers.get("X-CSRF-Token", "")
    except Exception:
        _login_failures += 1
        _next_login_at = time.monotonic() + min(60 * 2 ** (_login_failures - 1), LOGIN_BACKOFF_MAX)
        raise
    _login_failures, _next_login_at = 0, 0.0
    log("logged in")


def fetch_ustorage():
    # An expired session gets a 401, or a 200 with `ustorage` left out
    # (the unauthenticated view), so either one triggers a single re-login.
    for attempt in (1, 2):
        try:
            with _request("/api/system") as resp:
                system = json.load(resp)
            if "ustorage" in system:
                return system["ustorage"]
        except urllib.error.HTTPError as err:
            if err.code not in (401, 403) or attempt == 2:
                raise
        if attempt == 1:
            login()
    raise RuntimeError("/api/system has no ustorage block after login")


def _esc(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**labels):
    return "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items()) + "}"


class Metrics:
    def __init__(self):
        self._families = {}

    def add(self, name, help_text, value, **labels):
        if value is None:
            return
        value = float(value)
        if value.is_integer():
            value = int(value)  # byte counts must not lose digits to float formatting
        family = self._families.setdefault(name, (help_text, []))
        family[1].append(f"{name}{_labels(**labels) if labels else ''} {value}")

    def render(self):
        out = []
        for name, (help_text, samples) in self._families.items():
            out += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge", *samples]
        return "\n".join(out) + "\n"


def _match(value, healthy_value):
    # A missing field is no sample, not an unhealthy disk.
    return None if value is None else int(value == healthy_value)


def collect():
    try:
        return _render(fetch_ustorage())
    except Exception as err:  # noqa: BLE001 - fetch or an unexpected payload shape both mean up=0
        log(f"scrape failed: {type(err).__name__}: {err}")
        m = Metrics()
        m.add("unifi_storage_up", "1 if the console's storage data was read", 0)
        return m.render()


def _render(ustorage):
    m = Metrics()
    m.add("unifi_storage_up", "1 if the console's storage data was read", 1)
    disks = [d for d in ustorage.get("disks") or [] if d.get("model")]
    m.add("unifi_storage_disks", "Disks present in the console's bays", len(disks))
    for d in disks:
        slot = d.get("slot", "")
        m.add("unifi_storage_disk_info", "Disk identity and raw state strings", 1,
              slot=slot, model=d.get("model", ""), serial=d.get("serial", ""),
              firmware=d.get("firmware", ""), type=d.get("type", ""),
              state=d.get("state", ""), healthy=d.get("healthy", ""))
        m.add("unifi_storage_disk_healthy", "1 if UniFi OS rates the disk good", _match(d.get("healthy"), "good"), slot=slot)
        m.add("unifi_storage_disk_bad_sectors", "Bad sector count (UNC errors on the Storage page)", d.get("bad_sector"), slot=slot)
        m.add("unifi_storage_disk_life_span_percent", "Remaining rated endurance", d.get("life_span"), slot=slot)
        m.add("unifi_storage_disk_temperature_celsius", "Disk temperature", d.get("temperature"), slot=slot)
        m.add("unifi_storage_disk_power_on_hours", "Disk power-on hours", d.get("poweronhrs"), slot=slot)

    for s in ustorage.get("space") or []:
        labels = {"device": s.get("device", ""), "space_type": s.get("space_type", "")}
        m.add("unifi_storage_volume_healthy", "1 if UniFi OS rates the volume healthy", _match(s.get("health"), "health"), **labels)
        m.add("unifi_storage_volume_errors", "Volume error count", s.get("error_count"), **labels)
        m.add("unifi_storage_volume_size_bytes", "Volume size", s.get("total_bytes"), **labels)
        m.add("unifi_storage_volume_used_bytes", "Volume bytes used", s.get("used_bytes"), **labels)
    return m.render()


def metrics_text():
    # Cache so a scrape burst doesn't hammer the console's login endpoint.
    global _cache
    with _cache_lock:
        if time.monotonic() - _cache[0] >= CACHE_SECONDS:
            _cache = (time.monotonic(), collect())
        return _cache[1]


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body, ctype = metrics_text().encode(), "text/plain; version=0.0.4"
        elif self.path == "/healthz":
            body, ctype = b"ok\n", "text/plain"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    log(f"listening on :{PORT}, console {BASE}")
    # Threaded so /healthz answers while a slow console holds up /metrics.
    http.server.ThreadingHTTPServer(("", PORT), Handler).serve_forever()
