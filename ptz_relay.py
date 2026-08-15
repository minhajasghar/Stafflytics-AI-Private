"""
PTZ Relay Script for Bridge PC

Instructions:
Run this script on the PC that is on the same local network as the camera.
It listens on port 5001 and forwards PTZ requests to the camera's local IP.

Usage:
  python ptz_relay.py
"""

from flask import Flask, request, jsonify
import requests
import logging
from requests.auth import HTTPDigestAuth

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('PTZ-Relay')

# Default hardcoded camera settings
# Change these if the local camera IP or credentials change
CAMERA_IP   = "192.168.50.251"
CAMERA_PORT = "80"
CAMERA_USER = "admin"
CAMERA_PASS = "L2DD2594"

# Dahua cameras may use any of these CGI paths depending on firmware version
# They are tried in order; the first that responds successfully is cached for speed.
DAHUA_CGI_PATHS = [
    "/cgi-bin/ptz.cgi",
    "/cgi-bin/camctrl.cgi",   # some older Dahua variants
    "/ISAPI/PTZCtrl/channels/1/continuous",  # Hikvision ISAPI (in case camera is HIK OEM)
]

# Cache the working auth / path after the first successful call
_working_auth = None   # Will be set to (auth_obj, path) on first success
_auth_options = None   # Lazy-built list of auth objects to try


def _get_auth_options():
    global _auth_options
    if _auth_options is None:
        _auth_options = [
            None,
            (CAMERA_USER, CAMERA_PASS),                    # Basic auth
            HTTPDigestAuth(CAMERA_USER, CAMERA_PASS),      # Digest auth (Dahua default)
        ]
    return _auth_options


@app.route('/ptz', methods=['POST', 'GET'])
def ptz_relay():
    global _working_auth

    query_string = request.query_string.decode('utf-8')
    action = request.args.get('action', '')
    code   = request.args.get('code', '')

    base = f"http://{CAMERA_IP}:{CAMERA_PORT}"

    # Fast path: use cached working auth+path from previous successful call
    if _working_auth:
        auth_obj, cgi_path = _working_auth
        url = f"{base}{cgi_path}?{query_string}"
        try:
            r = requests.get(url, auth=auth_obj, timeout=4)
            if r.status_code in (200, 204) or 'OK' in r.text.upper():
                logger.info(f"PTZ OK [{action} {code}] -> {r.status_code}")
                return "OK", 200
            # If it stopped working, fall through to discovery
            logger.warning(f"Cached path failed ({r.status_code}), rediscovering...")
            _working_auth = None
        except Exception as e:
            logger.warning(f"Cached path error: {e}, rediscovering...")
            _working_auth = None

    # Discovery loop: try all CGI paths x all auth methods
    last_err = "No response from camera"
    for cgi_path in DAHUA_CGI_PATHS:
        url = f"{base}{cgi_path}?{query_string}"
        for auth in _get_auth_options():
            try:
                r = requests.get(url, auth=auth, timeout=5)
                logger.info(f"Tried {url} auth={type(auth).__name__} -> {r.status_code}")
                if r.status_code == 401:
                    last_err = f"Auth rejected at {cgi_path}"
                    continue
                if r.status_code in (200, 204) or 'OK' in r.text.upper():
                    _working_auth = (auth, cgi_path)
                    logger.info(f"PTZ success! Caching: path={cgi_path} auth={type(auth).__name__}")
                    return "OK", 200
                last_err = f"HTTP {r.status_code} at {cgi_path}"
            except requests.exceptions.ConnectTimeout:
                last_err = f"Connect timeout to {CAMERA_IP}:{CAMERA_PORT} — check firewall/IP"
                logger.warning(last_err)
                break   # No point trying other auth if TCP connection itself fails
            except requests.exceptions.ReadTimeout:
                last_err = f"Read timeout at {cgi_path} — camera accepted TCP but didn't reply (HTTP may be disabled)"
                logger.warning(last_err)
                break
            except Exception as e:
                last_err = str(e)[:120]
                continue

    logger.error(f"All PTZ paths failed: {last_err}")
    return jsonify({"status": "error", "message": last_err}), 502


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "camera": f"{CAMERA_IP}:{CAMERA_PORT}", "cached_path": _working_auth[1] if _working_auth else None})


if __name__ == '__main__':
    print("==========================================")
    print(" Stafflytics PTZ Relay Server (Bridge PC) ")
    print("==========================================")
    print(f"Target Camera: {CAMERA_IP}:{CAMERA_PORT}")
    print(f"CGI paths to try: {DAHUA_CGI_PATHS}")
    print("Listening on 0.0.0.0:5001 for VPS commands...")
    print()
    print("TIP: If you see 'Read timeout' in logs, your camera's HTTP")
    print("     management interface may be on a different port (e.g. 8000)")
    print("     or disabled. Check the camera's web UI port in its settings.")
    app.run(host='0.0.0.0', port=5001)
