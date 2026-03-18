
import socket

def listen_udp(port=5005):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(5)
    print(f"Listening for UDP on port {port}...")
    try:
        data, addr = sock.recvfrom(4096)
        print(f"Received {len(data)} bytes from {addr}")
        # Could unpack here if needed, but just seeing data is enough verification
    except socket.timeout:
        print("Timed out waiting for UDP packets.")
    finally:
        sock.close()

if __name__ == "__main__":
    listen_udp()
