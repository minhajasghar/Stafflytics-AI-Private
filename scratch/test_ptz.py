import requests
import os, hashlib, base64, time
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

CAMERA_IP = "192.168.50.251"
CAMERA_PORT = 80
CAMERA_USER = "admin"
CAMERA_PASS = "L2DD2594"

# 1. Get offset
r = requests.post(f"http://{CAMERA_IP}:{CAMERA_PORT}/onvif/device_service", 
                  data='<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/></s:Body></s:Envelope>'.encode('utf-8'),
                  headers={'Content-Type': 'application/soap+xml; charset=utf-8'}, timeout=3)
root = ET.fromstring(r.text)
utc_elem = root.find('.//{*}UTCDateTime')
h = int(utc_elem.find('{*}Time/{*}Hour').text)
m = int(utc_elem.find('{*}Time/{*}Minute').text)
s = int(utc_elem.find('{*}Time/{*}Second').text)
year = int(utc_elem.find('{*}Date/{*}Year').text)
month = int(utc_elem.find('{*}Date/{*}Month').text)
day = int(utc_elem.find('{*}Date/{*}Day').text)
cam_dt = datetime(year, month, day, h, m, s, tzinfo=timezone.utc)
offset_seconds = (cam_dt - datetime.now(timezone.utc)).total_seconds()
print("Camera clock offset (seconds):", offset_seconds)

def send_onvif(path, body):
    cam_now = datetime.fromtimestamp(time.time() + offset_seconds, tz=timezone.utc)
    ts_str = cam_now.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    nonce = os.urandom(16)
    pwd_digest = base64.b64encode(hashlib.sha1(nonce + ts_str.encode('utf-8') + CAMERA_PASS.encode('utf-8')).digest()).decode('utf-8')
    nonce_b64 = base64.b64encode(nonce).decode('utf-8')
    sec = f"""<s:Header>
        <Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
            <UsernameToken>
                <Username>{CAMERA_USER}</Username>
                <Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{pwd_digest}</Password>
                <Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_b64}</Nonce>
                <Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{ts_str}</Created>
            </UsernameToken>
        </Security>
    </s:Header>"""
    soap = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
    {sec}
    <s:Body>{body}</s:Body>
</s:Envelope>"""
    return requests.post(f"http://{CAMERA_IP}:{CAMERA_PORT}{path}", data=soap.encode('utf-8'), headers={'Content-Type': 'application/soap+xml; charset=utf-8'}, timeout=5)

# Test PTZ Move
body_move = """<ContinuousMove xmlns="http://www.onvif.org/ver20/ptz/wsdl">
    <ProfileToken>Profile000</ProfileToken>
    <Velocity>
        <PanTilt xmlns="http://www.onvif.org/ver10/schema" x="0.3" y="0.0" space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"/>
    </Velocity>
</ContinuousMove>"""
r_move = send_onvif('/onvif/ptz_service', body_move)
print("PTZ Move Right Status:", r_move.status_code)
time.sleep(0.5)

# Test PTZ Stop
body_stop = """<Stop xmlns="http://www.onvif.org/ver20/ptz/wsdl">
    <ProfileToken>Profile000</ProfileToken>
    <PanTilt>true</PanTilt>
    <Zoom>true</Zoom>
</Stop>"""
r_stop = send_onvif('/onvif/ptz_service', body_stop)
print("PTZ Stop Status:", r_stop.status_code)
