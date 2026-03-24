#!/bin/bash
# bootstrap_edge.sh
# PURPOSE: Start the Optical Radar edge node + camera stream on a Raspberry Pi.
# USAGE:   bash bootstrap_edge.sh          (manual)
#          Runs automatically on boot via optical-radar-edge.service (systemd)
#
# DEPLOYMENT (one-time setup on the RPi):
#   1. Copy this file to:  /home/pi/optical_radar/bootstrap_edge.sh
#   2. Make executable:    chmod +x /home/pi/optical_radar/bootstrap_edge.sh
#   3. Set server IP:      echo "169.254.9.75" > /home/pi/optical_radar/server.conf
#   4. Install service:    sudo cp optical-radar-edge.service /etc/systemd/system/
#   5. Enable service:     sudo systemctl daemon-reload && sudo systemctl enable optical-radar-edge
#   6. Reboot to test:     sudo reboot
#
# LOGS:
#   Node log:   /home/pi/optical_radar/node.log
#   Stream log: /home/pi/optical_radar/stream.log

set -e

# ─── Configuration ───────────────────────────────────────────────────────────
INSTALL_DIR="/home/pi/optical_radar"
CODE_DIR="$INSTALL_DIR/code"
SERVER_CONF_FILE="$INSTALL_DIR/server.conf"
NODE_CONF_FILE="$INSTALL_DIR/node.conf"
NODE_LOG="$INSTALL_DIR/node.log"

# Default Camera ID if node.conf is missing
CAMERA_ID="cam_pi"
if [ -f "$NODE_CONF_FILE" ]; then
    CAMERA_ID=$(head -1 "$NODE_CONF_FILE" | tr -d '[:space:]')
fi

SERVER_PORT=5005
STREAM_PORT=8000

echo "--- Optical Radar Edge Bootstrap ---"
echo "  Camera ID: $CAMERA_ID"

# ─── Step 1: Resolve Server IP ──────────────────────────────────────────────
# Priority: 1) server.conf  2) mDNS fallback  3) gateway scan
echo "[1/4] Resolving server IP..."

SERVER_IP=""

# Method 1: Config file (recommended)
if [ -f "$SERVER_CONF_FILE" ]; then
    SERVER_IP=$(head -1 "$SERVER_CONF_FILE" | tr -d '[:space:]')
    if [ -n "$SERVER_IP" ]; then
        echo "  Server IP from config: $SERVER_IP"
    fi
fi

# Method 2: mDNS fallback (try to resolve the laptop hostname)
if [ -z "$SERVER_IP" ]; then
    echo "  server.conf not found or empty. Trying mDNS fallback..."
    # Try common Windows hostnames; user can customize
    for HOSTNAME in "LAPTOP.local" "DESKTOP.local"; do
        RESOLVED=$(getent hosts "$HOSTNAME" 2>/dev/null | awk '{print $1}')
        if [ -n "$RESOLVED" ]; then
            SERVER_IP="$RESOLVED"
            echo "  Resolved $HOSTNAME -> $SERVER_IP"
            break
        fi
    done
fi

# Method 3: Gateway fallback (Wi-Fi or Ethernet)
if [ -z "$SERVER_IP" ]; then
    echo "  mDNS failed. Trying default gateway..."
    # Get the default gateway on any active interface (wlan0 or eth0)
    GW=$(ip route show default 2>/dev/null | grep -oP 'via \K[\d.]+' | head -1)
    if [ -n "$GW" ]; then
        SERVER_IP="$GW"
        echo "  Using gateway: $SERVER_IP"
    fi
fi

if [ -z "$SERVER_IP" ]; then
    echo "ERROR: Could not determine server IP address."
    echo "  Please create $SERVER_CONF_FILE with the server's IP address."
    echo "  Example: echo '192.168.1.100' > $SERVER_CONF_FILE"
    exit 1
fi

echo "  -> Server target: $SERVER_IP:$SERVER_PORT"

# ─── Step 2: Verify directories exist ───────────────────────────────────────
echo "[2/4] Verifying installation..."

if [ ! -d "$CODE_DIR" ]; then
    echo "ERROR: Code directory not found at $CODE_DIR"
    echo "  Deploy the code first. See README for instructions."
    exit 1
fi

if [ ! -d "$CODE_DIR/rpi" ]; then
    echo "ERROR: RPi module not found at $CODE_DIR/rpi"
    exit 1
fi

echo "  Installation OK: $CODE_DIR"

# ─── Step 3: Kill old processes ──────────────────────────────────────────────
echo "[3/4] Cleaning up old processes..."

pkill -f "python3 -m rpi.rpi_node" 2>/dev/null && echo "  Killed old rpi_node" || true
sleep 1

# ─── Step 4: Launch Edge Node + Camera Stream ───────────────────────────────
echo "[4/4] Launching edge node (tracking + streaming)..."

cd "$CODE_DIR"
export PYTHONPATH="$CODE_DIR"

# Start the edge node (motion detection + telemetry + HTTP stream)
nohup python3 -m rpi.rpi_node \
    --id "$CAMERA_ID" \
    --server "$SERVER_IP" \
    --port "$SERVER_PORT" \
    --mode "stream" \
    > "$NODE_LOG" 2>&1 &
NODE_PID=$!
echo "  RPi Node started (PID: $NODE_PID) -> $NODE_LOG"

# Brief health check
sleep 2
if kill -0 "$NODE_PID" 2>/dev/null; then
    echo "  [OK] RPi Node is running"
else
    echo "  [FAIL] RPi Node exited early. Check $NODE_LOG"
fi

echo ""
echo "--- Edge Bootstrap Complete! ---"
echo "  Camera ID:     $CAMERA_ID"
echo "  Server target: $SERVER_IP:$SERVER_PORT"
echo "  Stream:        http://$(hostname -I | awk '{print $1}'):$STREAM_PORT"
echo "  Node log:      $NODE_LOG"
