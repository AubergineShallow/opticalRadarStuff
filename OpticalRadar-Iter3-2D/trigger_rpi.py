import socket
import time
import threading

def sniff():
    print("Sniffing for UDP on 5005...")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 5005))
    s.settimeout(10)
    try:
        data, addr = s.recvfrom(1024)
        print(f"Captured packet from {addr}")
    except socket.timeout:
        print("No packets captured.")
    finally:
        s.close()

if __name__ == "__main__":
    t = threading.Thread(target=sniff)
    t.start()
    
    # Send a broadcast to trigger ARP/response
    print("Sending broadcast to 169.254.255.255...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(b"HELLO", ("169.254.255.255", 5005))
    sock.close()
    
    t.join()
