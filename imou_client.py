"""
Imou Open Platform client for Stafflytics.

This module ports the *working* logic from the standalone test project
(D:\\Desktop\\New folder\\imou_test.py + stream_server.py), which is confirmed
to authenticate (MD5-signed accessToken), bind the device and produce a live
HLS URL. We keep that exact request/signature/caching behaviour here instead of
re-inventing it.

Credentials are read from the environment (.env) only:
  IMOU_APP_ID, IMOU_APP_SECRET, IMOU_BASE_URL, IMOU_DEVICE_SERIAL, IMOU_CHANNEL_ID

Known issue handled here: Imou HLS live URLs are only valid for a short window
and the stream can hang/freeze after ~10s of continuous playback. We therefore:
  * cache the live URL but treat it as stale after LIVE_URL_TTL
  * re-bind / re-fetch the live URL on demand (force=True) whenever a playlist
    fetch fails, returns an empty list, or the bridge watchdog reports a stall
  * auto-refresh the accessToken before it expires (same 60s margin as the
    reference stream_server)
"""

import hashlib
import json
import threading
import time
import urllib.parse
import uuid

import requests

# Error codes we react to programmatically.
CODE_OK = "0"
CODE_LIVE_ALREADY_EXISTS = "LV1001"

# Token is considered stale 60s before its reported expiry (reference behaviour).
TOKEN_REFRESH_MARGIN = 60
# Imou live URLs expire quickly; treat as stale after this many seconds.
LIVE_URL_TTL = 10 * 60
# Playlist segment URLs inside the m3u8 must be reachable from the same host
# that requested the playlist. callers pass their own base (request.host_url).
TIMEOUT = 30


class ImouError(RuntimeError):
    """Raised for any API-level failure, carrying the Imou code + message."""

    def __init__(self, code, msg):
        super().__init__("Imou %s: %s" % (code, msg))
        self.code = code
        self.msg = msg


def load_imou_config():
    """Read the Imou settings from the environment. Returns a dict."""
    return {
        "app_id": (os_environ("IMOU_APP_ID") or "").strip(),
        "app_secret": (os_environ("IMOU_APP_SECRET") or "").strip(),
        "base_url": (os_environ("IMOU_BASE_URL") or "").strip(),
        "device_id": (os_environ("IMOU_DEVICE_SERIAL") or "").strip(),
        "channel_id": (os_environ("IMOU_CHANNEL_ID") or "").strip(),
    }


def os_environ(key):
    import os
    return os.environ.get(key, "")


def imou_enabled():
    cfg = load_imou_config()
    return bool(cfg["app_id"] and cfg["app_secret"] and cfg["device_id"])


def make_sign(app_secret, ts, nonce):
    """MD5 signature — exact formula from the working test project."""
    raw = "time:{0},nonce:{1},appSecret:{2}".format(ts, nonce, app_secret)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def call_api(base_url, app_id, app_secret, method, params):
    """POST to the Imou Open Platform API with a signed system header."""
    ts = int(time.time())
    nonce = str(uuid.uuid4())
    sign = make_sign(app_secret, ts, nonce)
    payload = {
        "system": {
            "ver": "1.0",
            "appId": app_id,
            "sign": sign,
            "time": ts,
            "nonce": nonce,
        },
        "id": str(uuid.uuid4()),
        "params": params,
    }
    url = base_url.rstrip("/") + "/" + method
    resp = requests.post(url, json=payload, timeout=TIMEOUT)
    try:
        body = resp.json()
    except Exception:
        raise ImouError("HTTP%s" % resp.status_code, "non-JSON response: %s" % resp.text[:200])
    result = body.get("result", {}) or {}
    code = result.get("code")
    if code is not None and str(code) != CODE_OK:
        raise ImouError(str(code), str(result.get("msg", "unknown error")))
    return result.get("data")


class ImouClient:
    """Thread-safe Imou client with token caching/refresh and live-URL management."""

    def __init__(self, cfg=None):
        self.cfg = cfg or load_imou_config()
        self.lock = threading.Lock()
        self._token = None
        self._token_expire = 0.0
        self._live_url = None
        self._live_url_set_at = 0.0

    # ---- accessToken ----------------------------------------------------

    def _fetch_token(self):
        data = call_api(
            self.cfg["base_url"], self.cfg["app_id"], self.cfg["app_secret"],
            "accessToken", {},
        )
        token = data["accessToken"]
        expire = int(data.get("expireTime", 259200))
        return token, time.time() + expire

    def _ensure_token_locked(self):
        """Must be called while self.lock is held."""
        if self._token and time.time() < self._token_expire - TOKEN_REFRESH_MARGIN:
            return self._token
        self._token, self._token_expire = self._fetch_token()
        return self._token

    def get_token(self):
        """Return a valid accessToken, refreshing before expiry (60s margin)."""
        with self.lock:
            return self._ensure_token_locked()

    # ---- live URL -------------------------------------------------------

    def _fetch_live_url(self):
        token = self._ensure_token_locked()
        try:
            data = call_api(
                self.cfg["base_url"], self.cfg["app_id"], self.cfg["app_secret"],
                "bindDeviceLive",
                {
                    "token": token,
                    "deviceId": self.cfg["device_id"],
                    "channelId": str(self.cfg["channel_id"]),
                    "streamId": 0,
                },
            )
        except ImouError as exc:
            # LV1001 = a live address already exists → fetch the existing one.
            if exc.code == CODE_LIVE_ALREADY_EXISTS:
                data = call_api(
                    self.cfg["base_url"], self.cfg["app_id"], self.cfg["app_secret"],
                    "getLiveStreamInfo",
                    {
                        "token": token,
                        "deviceId": self.cfg["device_id"],
                        "channelId": str(self.cfg["channel_id"]),
                    },
                )
            else:
                raise

        streams = (data or {}).get("streams", []) or []
        live = None
        for s in streams:
            if str(s.get("streamId")) == "0" and str(s.get("hls", "")).startswith("http://"):
                live = s["hls"]
                break
        if not live:
            for s in streams:
                if str(s.get("streamId")) == "0":
                    live = s.get("hls")
                    break
        if not live:
            for s in streams:
                if s.get("hls"):
                    live = s["hls"]
                    break
        if not live:
            raise ImouError("NOSTREAM", "no HLS url in response: %s" % json.dumps(data or {}))
        return live

    def get_live_url(self, force=False):
        """Return the cached live URL, or fetch/refresh one.

        force=True discards the cached URL and re-binds the live stream (used
        when a playlist fetch failed or a stall was detected).
        """
        with self.lock:
            cached_fresh = (
                self._live_url
                and not force
                and time.time() - self._live_url_set_at < LIVE_URL_TTL
            )
            if cached_fresh:
                return self._live_url
            self._live_url = self._fetch_live_url()
            self._live_url_set_at = time.time()
            return self._live_url

    # ---- playlist / segment helpers --------------------------------------

    def fetch_playlist(self, base_url, force=False):
        """Fetch the Imou m3u8. On failure with a stale URL, refresh the live
        URL once and retry. Returns (playlist_text, live_url_used)."""
        live = self.get_live_url(force=force)
        try:
            r = requests.get(live, timeout=20)
            if r.ok and _playlist_has_segments(r.text):
                return r.text, live
        except Exception:
            pass

        if force:
            raise ImouError("NOPLAYLIST", "playlist fetch failed after live-url refresh")

        # First attempt failed on a (possibly) stale URL → force refresh + retry.
        return self.fetch_playlist(base_url, force=True)

    def fetch_segment(self, seg_url):
        r = requests.get(seg_url, timeout=30, stream=True)
        r.raise_for_status()
        return r.raw


def _playlist_has_segments(text):
    """True when the playlist text contains at least one non-comment line."""
    if not text:
        return False
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return True
    return False


def rewrite_playlist(playlist_text, live_url, request_base):
    """Rewrite the Imou m3u8 so every segment URI points back at our local
    proxy (handles CORS + expiring signed segment URLs + cross-host access).
    """
    lines = []
    for line in playlist_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            lines.append(line)
            continue
        seg_url = urllib.parse.urljoin(live_url, line)
        proxied = request_base.rstrip("/") + "/api/stream/segment?u=" + urllib.parse.quote(seg_url, safe="")
        lines.append(proxied)
    return "\n".join(lines) + "\n"
