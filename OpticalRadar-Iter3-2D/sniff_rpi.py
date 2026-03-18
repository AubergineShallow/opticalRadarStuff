import socket
import struct
import time

def sniff_udp():
    print("=== Listening for UDP 5005/5353 Traffic (30s) ===")
    
    # Create a raw socket to listen for UDP packets
    # Note: On Windows, this requires admin or specific socket options
    try:
        # Standard UDP socket bound to 0.0.0.0:5005
        # We use REUSEADDR to not conflict with the existing server
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 5005))
        sock.settimeout(30)
        
        print(f"Bound to port 5005. Waiting for packets...")
        
        start = time.time()
        count = 0
        while time.time() - start < 30:
            try:
                data, addr = sock.recvfrom(4096)
                print(f"[*] RECV from {addr}: {len(data)} bytes | First 10: {data[:10].hex()}")
                count += 1
            except socket.timeout:
                break
            except Exception as e:
                print(f"Recv Error: {e}")
                break
        
        print(f"Total packets captured: {count}")
        sock.close()
    except Exception as e:
        print(f"Socket Error: {e}")

if __name__ == "__main__":
    sniff_udp()
