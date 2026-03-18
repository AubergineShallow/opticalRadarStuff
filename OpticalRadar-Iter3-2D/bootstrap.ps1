# bootstrap.ps1
# ┌──────────────────────────────────────────────────────────────────────────┐
# │  DEPRECATED: This monolithic bootstrap has been replaced by:           │
# │    .\bootstrap_server.ps1  — Server backend + frontend (this machine)  │
# │    bootstrap_edge.sh       — RPi edge node (auto-starts on Pi boot)    │
# │  This file is kept for reference only. Use the new scripts instead.    │
# └──────────────────────────────────────────────────────────────────────────┘
# PURPOSE: Automate the startup of the Optical Radar system (Server + RPi Edge)

$ErrorActionPreference = "Stop"

Write-Host "--- Optical Radar Bootstrap V3 ---" -ForegroundColor Cyan

# 1. Discover Server IP (Physical Ethernet preferred)
Write-Host "[1/6] Discovering Server IP..."
$EthernetIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { 
    $_.InterfaceAlias -match "^Ethernet$" -and $_.IPAddress -like "169.254.*"
} | Select-Object -First 1).IPAddress

if (-not $EthernetIP) {
    # Fallback to any physical Ethernet
    $EthernetIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { 
        $_.InterfaceAlias -eq "Ethernet" -or $_.InterfaceAlias -match "Ethernet \d+"
    } | Select-Object -First 1).IPAddress
}

if (-not $EthernetIP) {
    # Last fallback: any non-virtual IP
    $EthernetIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "(WSL|Hyper-V|Loopback|Virtual)" } | Select-Object -First 1).IPAddress
}

if (-not $EthernetIP) {
    Write-Error "Could not determine Server IP address."
    exit 1
}
Write-Host "Server IP: $EthernetIP" -ForegroundColor Green

# 2. Check Raspberry Pi Connectivity
Write-Host "[2/6] Checking Raspberry Pi (raspberrypi.local)..."
if (Test-Connection -ComputerName "raspberrypi.local" -Count 1 -Quiet) {
    Write-Host "Raspberry Pi is ONLINE." -ForegroundColor Green
} else {
    Write-Warning "Raspberry Pi (raspberrypi.local) is UNREACHABLE. Ensure Ethernet cable is connected."
    # We continue anyway in case user wants to run server-only, but usually this is a failure
}

# 3. Stop existing processes to avoid port conflicts
Write-Host "[3/6] Cleaning up old processes (5000, 5005, 5173)..."
$Ports = @(5000, 5005, 5173, 5174)
foreach ($Port in $Ports) {
    $ProcId = (Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue).OwningProcess
    if ($ProcId) {
        Write-Host "Stopping process $ProcId on port $Port"
        Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
    }
    $ProcIdUdp = (Get-NetUDPEndpoint -LocalPort $Port -ErrorAction SilentlyContinue).OwningProcess
    if ($ProcIdUdp) {
        Write-Host "Stopping process $ProcIdUdp on port $Port (UDP)"
        Stop-Process -Id $ProcIdUdp -Force -ErrorAction SilentlyContinue
    }
}
# Also kill any python instances running our server
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*server_main.py*" } | Stop-Process -Force -ErrorAction SilentlyContinue

# 4. Launch Backend and Frontend
Write-Host "[4/6] Launching Backend Server and Frontend UI..."
# Use cmd /c to handle executables and batch files correctly
Start-Process "cmd.exe" -ArgumentList "/c python code\server\server_main.py --config config.yaml" -WorkingDirectory $PSScriptRoot -NoNewWindow
Start-Sleep -Seconds 2
Start-Process "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory "$PSScriptRoot\NEW-UI-V2" -NoNewWindow

# 5. Remote Launch RPi Node and Stream
Write-Host "[5/6] Launching Remote Edge Node (cam_pi) and Stream..."
$SSH_CMD = "python3 -m rpi.rpi_node --id cam_pi --server $EthernetIP --port 5005 > node.log 2>&1 & python3 ~/optical_radar/code/stream.py > stream.log 2>&1 &"
ssh pi@raspberrypi.local $SSH_CMD

# 6. Open Browser
Write-Host "[6/6] Opening Dashboard and Live Stream..."
Start-Sleep -Seconds 3 # Give Vite a moment to start
Start-Process "http://localhost:5173"
Start-Process "http://raspberrypi.local:8000"

Write-Host "--- Bootstrap Complete! ---" -ForegroundColor Cyan
Write-Host "Dashboard: http://localhost:5173"
Write-Host "Stream:    http://raspberrypi.local:8000"
