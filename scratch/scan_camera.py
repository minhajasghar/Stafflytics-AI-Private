import socket
import sys

active_ips = ["192.168.50.47", "192.168.50.52", "192.168.50.249"]
ports = [554, 80, 8080, 37777] # Common RTSP, ONVIF, and Dahua ports

print("Scanning active IPs for RTSP/ONVIF ports...")

for ip in active_ips:
    print(f"\nChecking {ip}...")
    for port in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        result = s.connect_ex((ip, port))
        if result == 0:
            print(f"  [OPEN] Port {port} is reachable on {ip}!")
        s.close()

print("\nScan complete.")
