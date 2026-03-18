"""
discover_mdns.py
Browse for SSH services (_ssh._tcp.local) to find the RPi.
"""
import socket
import sys
import time
from zeroconf import Zeroconf, ServiceBrowser

class MyListener:
    def remove_service(self, zeroconf, type, name):
        print(f"Service {name} removed")

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            print(f"Service {name} added, service info: {info}")
            for addr in info.addresses:
                print(f"  IP: {socket.inet_ntoa(addr)}")

if __name__ == "__main__":
    print("Searching for Zeroconf services (_ssh._tcp.local)...")
    zeroconf = Zeroconf()
    listener = MyListener()
    browser = ServiceBrowser(zeroconf, "_ssh._tcp.local", listener)
    
    try:
        time.sleep(10)
    finally:
        zeroconf.close()
