import socket
from typing import Any

def send_packet(socket_obj: socket.socket, packet: Any, address: str, port: int) -> bool:
    """Send packet to server.

    Args:
        socket_obj: UDP socket to use for sending.
        packet: Packet object that has a pack() method.
        address: Server IP address.
        port: Server UDP port.

    Returns:
        bool: True if sent successfully, False otherwise.
    """
    if not socket_obj:
        return False

    try:
        data = packet.pack()
        socket_obj.sendto(data, (address, port))
        return True
    except Exception as e:
        print(f"Send failed: {e}")
        return False
