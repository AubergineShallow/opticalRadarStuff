import socket
import concurrent.futures
import subprocess

def check_ssh(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex((ip, 22))
        s.close()
        if result == 0:
            return ip
    except:
        pass
    return None

def get_ethernet_ips():
    # Attempt to find common link-local ranges or assigned IPs
    try:
        # We start with the known Ethernet interface alias 'Ethernet' or '169.254.9.75'
        # Let's just scan 169.254.x.x
        print("Starting sweep of 169.254.x.x (Sampling)...")
        # Link-local blocks are 169.254.0.0/16
        # We'll scan in blocks to be faster. 
        # Usually RPi is in high ranges like 169.254.212.x or 169.254.9.x
        subnets = [212, 9, 213, 8, 0, 1]
        ips = []
        for s in subnets:
            ips.extend([f"169.254.{s}.{i}" for i in range(1, 255)])
        return ips
    except Exception as e:
        print(f"Error getting base IPs: {e}")
        return []

if __name__ == "__main__":
    print("=== Raspberry Pi Link-Local Discovery ===")
    ips_to_scan = get_ethernet_ips()
    
    found = []
    print(f"Scanning {len(ips_to_scan)} candidate IPs...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=200) as executor:
        futures = {executor.submit(check_ssh, ip): ip for ip in ips_to_scan}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                found.append(res)
                print(f"[*] Found SSH on {res}")

    if not found:
        print("No SSH found in specific subnets. Scanning sampling of entire 169.254.0.0/16...")
        all_samples = [f"169.254.{j}.{i}" for j in range(0, 256) for i in range(1, 255, 5)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=200) as executor:
            futures = {executor.submit(check_ssh, ip): ip for ip in all_samples}
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    found.append(res)
                    print(f"[*] Found SSH on {res}")

    if found:
        print(f"\nSUCCESS: Found RPi candidate(s): {found}")
    else:
        print("\nFAILURE: Could not find any device with SSH enabled on 169.254.x.x")
        print("Check if the Pi's green activity light is on and Ethernet port link light is active.")
