"""
mini_dhcp_server.py
A minimal DHCP server to give the RPi an IP on a direct Ethernet link.
Assigns 169.254.9.100 to the first requester.
"""
import socket
import struct

def get_dhcp_offer(xid, chaddr):
    # DHCP Offer Packet
    packet = bytearray(240)
    # op (2 = reply), htype (1 = ethernet), hlen (6), hops (0)
    packet[0:4] = struct.pack('!BBBB', 2, 1, 6, 0)
    # xid
    packet[4:8] = xid
    # secs (0), flags (0)
    packet[8:12] = b'\x00\x00\x00\x00'
    # ciaddr (0)
    # yiaddr (169.254.9.100)
    packet[16:20] = socket.inet_aton("169.254.9.100")
    # siaddr (169.254.9.75)
    packet[20:24] = socket.inet_aton("169.254.9.75")
    # giaddr (0)
    # chaddr (6 bytes) + padding (10 bytes)
    packet[28:34] = chaddr
    # Magic cookie
    packet[236:240] = b'\x63\x82\x53\x63'
    # DHCP Options
    # Opt 53: DHCP Offer (1 byte: 0x02)
    packet += b'\x35\x01\x02'
    # Opt 1: Subnet Mask (255.255.0.0)
    packet += b'\x01\x04\xff\xff\x00\x00'
    # Opt 3: Router (169.254.9.75)
    packet += b'\x03\x04' + socket.inet_aton("169.254.9.75")
    # Opt 51: Lease Time (1 hour)
    packet += b'\x33\x04\x00\x00\x0e\x10'
    # Opt 54: Server ID (169.254.9.75)
    packet += b'\x36\x04' + socket.inet_aton("169.254.9.75")
    # End
    packet += b'\xff'
    return packet

def get_dhcp_ack(xid, chaddr):
    # DHCP Ack Packet
    packet = bytearray(240)
    # op (2 = reply), htype (1 = ethernet), hlen (6), hops (0)
    packet[0:4] = struct.pack('!BBBB', 2, 1, 6, 0)
    # xid
    packet[4:8] = xid
    # yiaddr (169.254.9.100)
    packet[16:20] = socket.inet_aton("169.254.9.100")
    # siaddr (169.254.9.75)
    packet[20:24] = socket.inet_aton("169.254.9.75")
    # chaddr
    packet[28:34] = chaddr
    # Magic cookie
    packet[236:240] = b'\x63\x82\x53\x63'
    # DHCP Options
    # Opt 53: DHCP Ack (1 byte: 0x05)
    packet += b'\x35\x01\x05'
    # Opt 1: Subnet Mask (255.255.0.0)
    packet += b'\x01\x04\xff\xff\x00\x00'
    # Opt 3: Router
    packet += b'\x03\x04' + socket.inet_aton("169.254.9.75")
    # Opt 51: Lease Time (1 hour)
    packet += b'\x33\x04\x00\x00\x0e\x10'
    # Opt 54: Server ID
    packet += b'\x36\x04' + socket.inet_aton("169.254.9.75")
    # End
    packet += b'\xff'
    return packet

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        server.bind(('', 67))
    except Exception as e:
        print(f"Error binding to port 67: {e}. Are you running as admin?")
        return

    print("DHCP Server started on port 67. Waiting for Discover...")
    while True:
        data, addr = server.recvfrom(2048)
        if data[0] == 1: # BOOTREQUEST
            xid = data[4:8]
            chaddr = data[28:34]
            mac = ':'.join(f'{b:02x}' for b in chaddr)
            
            # Find DHCP Message Type (Opt 53)
            msg_type = 0
            idx = 240
            while idx < len(data):
                opt_type = data[idx]
                if opt_type == 255: break
                opt_len = data[idx+1]
                if opt_type == 53:
                    msg_type = data[idx+2]
                    break
                idx += 2 + opt_len
            
            if msg_type == 1: # Discover
                print(f"DHCP Discover from MAC: {mac}")
                offer = get_dhcp_offer(xid, chaddr)
                server.sendto(offer, ('255.255.255.255', 68))
                print("Sent DHCP Offer for 169.254.9.100")
            elif msg_type == 3: # Request
                print(f"DHCP Request from MAC: {mac}")
                ack = get_dhcp_ack(xid, chaddr)
                server.sendto(ack, ('255.255.255.255', 68))
                print("Sent DHCP Ack for 169.254.9.100")

if __name__ == "__main__":
    main()
