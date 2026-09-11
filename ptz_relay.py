"""
Stafflytics PTZ Relay — ONVIF Edition with Auto Clock Synchronization
Connects to Dahua/Imou cameras and controls Pan/Tilt/Zoom reliably.
"""
from flask import Flask, request, jsonify
import requests
import hashlib
import base64
import os
import time
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('PTZ-ONVIF')

# Default Camera Settings
CAMERA_IP   = "192.168.50.251"
CAMERA_PORT = "80"
CAMERA_USER = "admin"
CAMERA_PASS = "L2DD2594"

# Cache ONVIF ProfileToken & Clock Offset
_onvif_profile_token = None
_cam_time_offset_seconds = 0.0
_last_clock_sync = 0.0

def sync_camera_clock():
    """Syncs time offset with camera to eliminate WS-Security timestamp errors"""
    global _cam_time_offset_seconds, _last_clock_sync
    try:
        url = f"http://{CAMERA_IP}:{CAMERA_PORT}/onvif/device_service"
        body = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
    <s:Body>
        <GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>
    </s:Body>
</s:Envelope>"""
        headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
        r = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=3)
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            utc_elem = root.find('.//{*}UTCDateTime')
            if utc_elem is not None:
                h = int(utc_elem.find('{*}Time/{*}Hour').text)
                m = int(utc_elem.find('{*}Time/{*}Minute').text)
                s = int(utc_elem.find('{*}Time/{*}Second').text)
                year = int(utc_elem.find('{*}Date/{*}Year').text)
                month = int(utc_elem.find('{*}Date/{*}Month').text)
                day = int(utc_elem.find('{*}Date/{*}Day').text)
                cam_dt = datetime(year, month, day, h, m, s, tzinfo=timezone.utc)
                _cam_time_offset_seconds = (cam_dt - datetime.now(timezone.utc)).total_seconds()
                _last_clock_sync = time.time()
                logger.info(f"Camera clock synchronized. Offset: {_cam_time_offset_seconds:.1f}s")
    except Exception as e:
        logger.warning(f"Failed to sync camera clock: {e}")

def get_ws_security_header(user, pwd):
    """Generates ONVIF WS-UsernameToken Security Header using camera-synced time"""
    if time.time() - _last_clock_sync > 300: # Re-sync every 5 mins
        sync_camera_clock()

    cam_now = datetime.fromtimestamp(time.time() + _cam_time_offset_seconds, tz=timezone.utc)
    timestamp = cam_now.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    nonce = os.urandom(16)
    pwd_digest = base64.b64encode(hashlib.sha1(nonce + timestamp.encode('utf-8') + pwd.encode('utf-8')).digest()).decode('utf-8')
    nonce_b64 = base64.b64encode(nonce).decode('utf-8')

    return f"""
    <s:Header>
        <Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
            <UsernameToken>
                <Username>{user}</Username>
                <Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{pwd_digest}</Password>
                <Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_b64}</Nonce>
                <Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{timestamp}</Created>
            </UsernameToken>
        </Security>
    </s:Header>
    """

def send_onvif_request(service_path, body_xml):
    url = f"http://{CAMERA_IP}:{CAMERA_PORT}{service_path}"
    headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
    
    soap_msg = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
    {get_ws_security_header(CAMERA_USER, CAMERA_PASS)}
    <s:Body>
        {body_xml}
    </s:Body>
</s:Envelope>"""

    r = requests.post(url, data=soap_msg.encode('utf-8'), headers=headers, timeout=5)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}: {r.text[:100]}")
    return r.text

def get_profile_token():
    """Fetches the primary Media ProfileToken from the camera"""
    global _onvif_profile_token
    if _onvif_profile_token:
        return _onvif_profile_token
        
    logger.info("Fetching ONVIF Profile Token...")
    sync_camera_clock()
    body = '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>'
    res = send_onvif_request('/onvif/media_service', body)
    
    root = ET.fromstring(res)
    profiles = root.findall('.//{*}Profiles')
    if not profiles:
        raise Exception("No ONVIF Media Profiles found.")
    
    _onvif_profile_token = profiles[0].attrib['token']
    logger.info(f"Obtained Profile Token: {_onvif_profile_token}")
    return _onvif_profile_token


@app.route('/ptz', methods=['POST', 'GET'])
def ptz_relay():
    action = request.args.get('action', '')
    code = request.args.get('code', '')

    try:
        token = get_profile_token()
        
        pan_speed = 0.0
        tilt_speed = 0.0
        speed_scalar = 0.5  # Adjust between 0.1 and 1.0
        
        if code == 'Up': tilt_speed = speed_scalar
        elif code == 'Down': tilt_speed = -speed_scalar
        elif code == 'Left': pan_speed = -speed_scalar
        elif code == 'Right': pan_speed = speed_scalar
        
        if action == 'start':
            body = f"""
            <ContinuousMove xmlns="http://www.onvif.org/ver20/ptz/wsdl">
                <ProfileToken>{token}</ProfileToken>
                <Velocity>
                    <PanTilt xmlns="http://www.onvif.org/ver10/schema" x="{pan_speed}" y="{tilt_speed}" space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"/>
                </Velocity>
            </ContinuousMove>
            """
            send_onvif_request('/onvif/ptz_service', body)
            logger.info(f"ONVIF ContinuousMove START: {code}")
            
        elif action == 'stop':
            body = f"""
            <Stop xmlns="http://www.onvif.org/ver20/ptz/wsdl">
                <ProfileToken>{token}</ProfileToken>
                <PanTilt>true</PanTilt>
                <Zoom>true</Zoom>
            </Stop>
            """
            send_onvif_request('/onvif/ptz_service', body)
            logger.info(f"ONVIF ContinuousMove STOP: {code}")

        return "OK", 200

    except Exception as e:
        logger.error(f"ONVIF PTZ Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 502

if __name__ == '__main__':
    print("==========================================")
    print(" Stafflytics PTZ Relay Server (ONVIF Mode)")
    print("==========================================")
    print(f"Target Camera: {CAMERA_IP}:{CAMERA_PORT}")
    print("Listening on 0.0.0.0:5003 for VPS commands...")
    sync_camera_clock()
    app.run(host='0.0.0.0', port=5003)
