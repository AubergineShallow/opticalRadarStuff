# bootstrap_server.ps1
# PURPOSE: Start the Optical Radar server backend + frontend UI on this Windows machine.
# USAGE:   .\bootstrap_server.ps1
#
# This script handles ONLY the server side. The RPi edge node starts automatically
# on boot via systemd (see bootstrap_edge.sh / optical-radar-edge.service).

$ErrorActionPreference = "Stop"

Write-Host "--- Optical Radar Server Bootstrap ---" -ForegroundColor Cyan

# ─── Step 0: Check Dependencies ──────────────────────────────────────────────
Write-Host "[0/4] Checking Dependencies..."
Write-Host "  Checking Python requirements..."
python -c "import pkg_resources; pkg_resources.require(open('requirements.txt').read())" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Missing Python packages. Installing..." -ForegroundColor Yellow
    python -m pip install -r requirements.txt
} else {
    Write-Host "  Python dependencies satisfied." -ForegroundColor Green
}

Write-Host "  Checking Node.js requirements..."
if (-not (Test-Path "$PSScriptRoot\NEW-UI-V2\node_modules")) {
    Write-Host "  Missing node_modules. Installing..." -ForegroundColor Yellow
    Push-Location "$PSScriptRoot\NEW-UI-V2"
    npm install
    Pop-Location
} else {
    Write-Host "  Node.js dependencies satisfied." -ForegroundColor Green
}

# ─── Step 1: Discover Server IP ──────────────────────────────────────────────
Write-Host "[1/4] Discovering Server IP..."

$EthernetIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { 
    $_.InterfaceAlias -match "^Ethernet$" -and $_.IPAddress -like "169.254.*"
} | Select-Object -First 1).IPAddress

if (-not $EthernetIP) {
    # Fallback: any physical Ethernet adapter
    $EthernetIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { 
        $_.InterfaceAlias -eq "Ethernet" -or $_.InterfaceAlias -match "Ethernet \d+"
    } | Select-Object -First 1).IPAddress
}

if (-not $EthernetIP) {
    # Last fallback: any non-virtual adapter
    $EthernetIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.InterfaceAlias -notmatch "(WSL|Hyper-V|Loopback|Virtual)"
    } | Select-Object -First 1).IPAddress
}

if (-not $EthernetIP) {
    Write-Error "Could not determine Server IP address."
    exit 1
}

Write-Host "Server IP: $EthernetIP" -ForegroundColor Green
Write-Host "  (If this is wrong, the RPi edge node may not be able to reach the server.)" -ForegroundColor DarkGray
Write-Host "  (Use this IP in the RPi's /home/pi/optical_radar/server.conf)" -ForegroundColor DarkGray

# ─── Step 2: Cleanup old processes ───────────────────────────────────────────
Write-Host "[2/4] Cleaning up old processes (ports 5000, 5005, 5173, 5174)..."

$Ports = @(5000, 5005, 3000)
foreach ($Port in $Ports) {
    $ProcId = (Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue).OwningProcess
    if ($ProcId) {
        Write-Host "  Stopping process $ProcId on port $Port (TCP)"
        Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
    }
    $ProcIdUdp = (Get-NetUDPEndpoint -LocalPort $Port -ErrorAction SilentlyContinue).OwningProcess
    if ($ProcIdUdp) {
        Write-Host "  Stopping process $ProcIdUdp on port $Port (UDP)"
        Stop-Process -Id $ProcIdUdp -Force -ErrorAction SilentlyContinue
    }
}

# Kill any lingering server_main.py
Get-Process -Name python -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*server_main.py*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue

# ─── Step 3: Launch Backend + Frontend ───────────────────────────────────────
Write-Host "[3/4] Launching Backend Server and Frontend UI..."

# Backend: Python server
Start-Process "cmd.exe" -ArgumentList "/c python code\server\server_main.py --config config.yaml" `
    -WorkingDirectory $PSScriptRoot -NoNewWindow
Start-Sleep -Seconds 2

# Frontend: Vite dev server
Start-Process "cmd.exe" -ArgumentList "/c npm run dev" `
    -WorkingDirectory "$PSScriptRoot\NEW-UI-V2" -NoNewWindow

# ─── Step 4: Open Dashboard ─────────────────────────────────────────────────
Write-Host "[4/4] Opening Dashboard..."
Start-Sleep -Seconds 3  # Give Vite a moment to start
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "--- Server Bootstrap Complete! ---" -ForegroundColor Cyan
Write-Host "Dashboard:  http://localhost:3000"
Write-Host "Server IP:  $EthernetIP (UDP port 5005)"
Write-Host ""
Write-Host "Make sure the RPi edge node knows this server IP." -ForegroundColor Yellow
Write-Host "On the RPi, set it in: /home/pi/optical_radar/server.conf" -ForegroundColor Yellow
