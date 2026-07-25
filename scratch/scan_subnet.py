import socket
import concurrent.futures

def check_ip(ip, port=554):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        result = s.connect_ex((ip, port))
        if result == 0:
            return ip
    except Exception:
        pass
    finally:
        s.close()
    return None

def main():
    subnet = "192.168.50"
    print(f"Scanning subnet {subnet}.1 to {subnet}.254 on port 554...")
    ips_to_scan = [f"{subnet}.{i}" for i in range(1, 255)]
    
    open_ips = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        results = executor.map(check_ip, ips_to_scan)
        for res in results:
            if res:
                open_ips.append(res)
                print(f"[FOUND] RTSP port 554 open on: {res}")
                
    print("\nScan completed.")
    print(f"IPs with port 554 open: {open_ips}")

if __name__ == "__main__":
    main()
