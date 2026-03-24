# Multi-Node Wi-Fi Deployment Guide

This guide details the setup for a wireless multi-node architecture using Raspberry Pi Edge nodes. Following this guide will enable seamless operation of multiple visual/sensor tracking edge nodes communicating wirelessly back to a centralized back-end server via Wi-Fi.

## Architecture Overview

*   **Central Server:** A back-end laptop or server running the Python tracking environment and the React/DeckGL dashboard.
*   **Edge Nodes (xN):** Raspberry Pi nodes (Pi 3, 4, or Zero 2 W) running the tracking algorithms locally, connected via Wi-Fi.
*   **Wi-Fi Router/AP:** A standard Wi-Fi router bridging the nodes and the central server. The central server can also be connected via Ethernet to this router.

## 1. Network Preparation (Router / Server)

1.  **Wi-Fi SSID & Password:** Ensure you have a dedicated 2.4GHz or 5GHz Wi-Fi network. All Edge Nodes and the Central Server must be on the same subnet.
2.  **Central Server IP:** Locate the IPv4 address of your central server (e.g., `192.168.1.100`).
    *   *Tip:* Set a static IP for your central server in your router settings to prevent it from changing.
3.  **Firewall:** Ensure your central server allows inbound UDP/TCP traffic on port `5005` (Tracking Data) and `8080` (WebSocket/Dashboard).

## 2. Raspberry Pi Configuration (Per Node)

Perform the following on *each* Raspberry Pi node:

### 2.1. Basic OS and Network Setup
1.  Flash Raspberry Pi OS (Bullseye or Bookworm, 64-bit recommended) using the Raspberry Pi Imager.
2.  During the imaging process (Advanced Options):
    *   Set the **Hostname** uniquely for each node (e.g., `radarnode-01`, `radarnode-02`).
    *   Enable **SSH**.
    *   Configure **Wireless LAN** with your router's SSID and Password.
3.  Boot the Raspberry Pi and connect via SSH: `ssh pi@radarnode-01.local`.

### 2.2. Clone the Repository
Clone the codebase onto the Pi:
```bash
cd ~
git clone <your-repo-url> optical_radar
cd optical_radar
```

### 2.3. Configure Node Settings
The bootstrap script relies on two key configuration files inside the `/home/pi/optical_radar/` directory:

1.  **Configure the Server IP (`server.conf`):**
    Tell the node where to send data.
    ```bash
    echo "192.168.1.100" > /home/pi/optical_radar/server.conf
    ```
    *(If omitted, the script will attempt mDNS fallback, and then fallback to the default gateway router IP).*

2.  **Configure the Node ID (`node.conf`):**
    Give the node a unique camera/tracker ID. **This is critical for multi-node setups.**
    ```bash
    echo "cam_pi_01" > /home/pi/optical_radar/node.conf
    ```
    *Note: Use `cam_pi_02`, `cam_pi_03`, etc. for subsequent nodes.*

### 2.4. Hardware Sensors (Optional)
If attaching the local hardware sensors (PIR, Touch, DHT11), wire them as follows (BCM numbering):
*   **LED:** GPIO 17
*   **PIR Motion:** GPIO 6
*   **Touch Sensor:** GPIO 5
*   **DHT11 Temp/Humidity:** GPIO 4

*(See `hardware_manager.py` for more details).*

## 3. Launching and Verification

### 3.1. Start the Central Server
On your backend machine:
```bash
python code/run_server.py
```
And launch the frontend dashboard (Node.js):
```bash
cd NEW-UI-V2
npm run dev
```

### 3.2. Start the Edge Nodes
On each Raspberry Pi, run the bootstrap script:
```bash
cd /home/pi/optical_radar
bash bootstrap_edge.sh
```
This will launch `rpi_node.py` in `stream` mode, automatically loading the `node.conf` ID and `server.conf` target.

### 3.3. Verification via Node Health Monitor
Check the server terminal or frontend dashboard. You should see `NODE_UPDATE` events indicating successful registration:
1.  **Online Status:** All nodes will appear in the dashboard's "Node Health" module.
2.  **Multi-Node IDs:** Ensure `cam_pi_01`, `cam_pi_02`, etc., are distinctly listed without overwriting each other.
3.  **Streaming:** Visit `http://<node-ip>:8000` to view the MJPEG debug stream for any given node to verify the camera angle and processing.

## 4. Automating Startup on Boot (Optional)

To ensure the nodes automatically connect to the network and start tracking on power-up, install the systemd service:

1.  Create the service file (if not already present):
    ```bash
    sudo nano /etc/systemd/system/optical-radar-edge.service
    ```
2.  Add the following contents:
    ```ini
    [Unit]
    Description=Optical Radar Edge Node
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=simple
    User=pi
    WorkingDirectory=/home/pi/optical_radar
    ExecStart=/bin/bash /home/pi/optical_radar/bootstrap_edge.sh
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target
    ```
3.  Enable and start the service:
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable optical-radar-edge.service
    sudo systemctl start optical-radar-edge.service
    ```

You can view live background logs using:
`journalctl -u optical-radar-edge.service -f`
