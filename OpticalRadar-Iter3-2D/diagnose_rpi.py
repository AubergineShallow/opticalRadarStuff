"""
diagnose_rpi.py
Quick UDP listener to discover what IP the RPi is sending from,
then SSH in and check camera + service status.
"""
import socket
import struct
import sys
import time

# Step 1: Listen on UDP 5005 to capture the sender IP
print("=== Step 1: Listening on UDP 5005 for RPi packets (10s timeout) ===")
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("0.0.0.0", 5006))  # Use 5006 to avoid conflict with running server
except OSError:
    print("Port 5006 busy, trying 5007...")
    sock.bind(("0.0.0.0", 5007))

sock.settimeout(10)

# We can't easily sniff the server's port, so let's just check ARP + try SSH
sock.close()

# Step 2: Get all interfaces and their IPs
print("\n=== Step 2: Network Interfaces ===")
import subprocess
result = subprocess.run(["powershell", "-Command", 
    "Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias, IPAddress | Format-Table -AutoSize"],
    capture_output=True, text=True)
print(result.stdout)

# Step 3: Scan for SSH on ethernet-adjacent IPs
print("\n=== Step 3: Quick SSH port scan on likely subnets ===")
import concurrent.futures

def check_ssh(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex((ip, 22))
        s.close()
        if result == 0:
            return ip
    except:
        pass
    return None

# Scan 169.254.x.x range (common link-local for direct Ethernet)
# Get the Ethernet interface IP first
candidates = []

# Check the 169.254.9.x subnet (our Ethernet adapter is 169.254.9.75)
print("Scanning 169.254.9.1-254 for SSH...")
ips_169 = [f"169.254.9.{i}" for i in range(1, 255)]

# Also check nearby subnets
print("Also scanning 169.254.212.x for SSH...")
ips_212 = [f"169.254.212.{i}" for i in range(1, 255)]

all_ips = ips_169 + ips_212

with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
    futures = {executor.submit(check_ssh, ip): ip for ip in all_ips}
    for future in concurrent.futures.as_completed(futures, timeout=15):
        result = future.result()
        if result:
            candidates.append(result)
            print(f"  FOUND SSH: {result}")

if not candidates:
    print("  No SSH hosts found in 169.254.9.x or 169.254.212.x")
    # Try broader scan
    print("\nScanning 169.254.0.1 - 169.254.255.254 (sampling every 10th IP)...")
    sample_ips = [f"169.254.{j}.{i}" for j in range(0, 256, 1) for i in range(1, 255, 10)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = {executor.submit(check_ssh, ip): ip for ip in sample_ips[:2000]}
        for future in concurrent.futures.as_completed(futures, timeout=30):
            result = future.result()
            if result:
                candidates.append(result)
                print(f"  FOUND SSH: {result}")

if candidates:
    print(f"\n=== Step 4: SSH into {candidates[0]} to check camera ===")
    # Try SSH with paramiko if available, otherwise use subprocess
    rpi_ip = candidates[0]
    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(rpi_ip, username='pi', password='123456789', timeout=5)
        
        commands = [
            ("Camera Detection (vcgencmd)", "vcgencmd get_camera 2>/dev/null || echo 'vcgencmd N/A'"),
            ("Camera Detection (libcamera)", "libcamera-hello --list-cameras 2>&1 | head -10"),
            ("Video Devices", "ls -la /dev/video* 2>/dev/null || echo 'no /dev/video devices'"),
            ("Service Status", "sudo systemctl status optical-radar-edge.service --no-pager 2>&1 | head -15"),
            ("Port 8000", "ss -tlnp | grep 8000 || echo 'port 8000 NOT listening'"),
            ("Running Processes", "ps aux | grep -E 'rpi_node|stream|python' | grep -v grep"),
            ("Node Log (last 15)", "tail -15 /home/pi/optical_radar/node.log 2>/dev/null || echo 'no node.log'"),
            ("Camera Test", "python3 -c \"import cv2; cap=cv2.VideoCapture(0); print('Camera opened:', cap.isOpened()); cap.release()\" 2>&1"),
        ]
        
        for label, cmd in commands:
            print(f"\n--- {label} ---")
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
            print(stdout.read().decode().strip())
            err = stderr.read().decode().strip()
            if err:
                print(f"  STDERR: {err}")
        
        ssh.close()
    except ImportError:
        print("paramiko not available, trying subprocess SSH...")
        for label, cmd in [
            ("Full Diagnostics", 
             "vcgencmd get_camera 2>/dev/null; "
             "ls -la /dev/video* 2>/dev/null || echo 'no video devs'; "
             "sudo systemctl status optical-radar-edge.service --no-pager 2>&1 | head -10; "
             "ss -tlnp | grep 8000 || echo 'port 8000 not listening'; "
             "ps aux | grep -E 'rpi_node|stream' | grep -v grep; "
             "tail -10 /home/pi/optical_radar/node.log 2>/dev/null")
        ]:
            print(f"\n--- {label} ---")
            r = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                 f"pi@{rpi_ip}", cmd],
                capture_output=True, text=True, timeout=15
            )
            print(r.stdout)
            if r.stderr:
                print(f"  STDERR: {r.stderr[:500]}")
    except Exception as e:
        print(f"SSH Error: {e}")
else:
    print("\n!!! Could not find RPi on the network via SSH scan !!!")
    print("The RPi may not have SSH enabled, or it's on a different subnet.")
    print("Try connecting directly via Ethernet and checking the Pi's IP.")
