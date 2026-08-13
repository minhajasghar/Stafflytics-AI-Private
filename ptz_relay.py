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
import urllib.parse
from requests.auth import HTTPDigestAuth
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('PTZ-Relay')

# Default hardcoded camera settings
# Change these if the local camera IP or credentials change
CAMERA_IP = "192.168.50.251"
CAMERA_PORT = "8080"
CAMERA_USER = "admin"
CAMERA_PASS = "L2DD2594"

@app.route('/ptz', methods=['POST', 'GET'])
def ptz_relay():
    # Forward the query parameters to the camera
    query_string = request.query_string.decode('utf-8')
    action = request.args.get('action')
    direction = request.args.get('code')
    
    url = f"http://{CAMERA_IP}:{CAMERA_PORT}/cgi-bin/ptz.cgi?{query_string}"
    
    auth_methods = [None, (CAMERA_USER, CAMERA_PASS), HTTPDigestAuth(CAMERA_USER, CAMERA_PASS)]
    
    last_err = ""
    for auth in auth_methods:
        try:
            r = requests.get(url, timeout=3, auth=auth)
            logger.info(f"Relayed to {url} -> status {r.status_code}")
            
            if r.ok or 'OK' in r.text:
                return "OK", 200
            
            if r.status_code == 401:
                continue # Try next auth method
                
            last_err = f"HTTP {r.status_code}: {r.text[:80]}"
            break
        except Exception as e:
            last_err = str(e)[:100]
            continue

    logger.error(f"Failed to relay PTZ: {last_err}")
    return jsonify({"status": "error", "message": last_err}), 502

if __name__ == '__main__':
    print("==========================================")
    print(" Stafflytics PTZ Relay Server (Bridge PC) ")
    print("==========================================")
    print(f"Target Camera: {CAMERA_IP}:{CAMERA_PORT}")
    print("Listening on 0.0.0.0:5001 for VPS commands...")
    app.run(host='0.0.0.0', port=5001)
