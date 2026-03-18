# SSH Guide: Connecting to Raspberry Pi via Ethernet (Windows)

When connecting a Raspberry Pi directly to your laptop via an Ethernet cable, the main challenge is that there is usually no DHCP server to assign an IP address. Here are the three best ways to connect.

## Method 1: The Hostname (Simplest)
Modern Raspberry Pi OS versions support **mDNS**, which allows you to use a hostname instead of an IP address.

1.  Connect the Ethernet cable.
2.  Wait about 30-60 seconds for the Pi to boot and initialize the network.
3.  Open PowerShell or Command Prompt on your laptop.
4.  Run the following command:
    ```bash
    ssh pi@raspberrypi.local
    ```
    *(Note: If you changed the hostname during setup, use `<your-hostname>.local`)*

## Method 2: Internet Connection Sharing (Recommended)
If you want the Pi to have internet access (through your laptop's WiFi) and want your laptop to act as a DHCP server (assigning a stable IP):

1.  Press `Win + R`, type `ncpa.cpl`, and hit Enter.
2.  Right-click your **WiFi** adapter and select **Properties**.
3.  Go to the **Sharing** tab.
4.  Check **"Allow other network users to connect through this computer's Internet connection"**.
5.  Select **Ethernet** from the dropdown menu.
6.  Click **OK**.
7.  Unplug and replug the Ethernet cable to the Pi.
8.  The Pi should now get an IP in the `192.168.137.x` range. You can use the hostname again or find the IP using `arp -a`.

## Method 3: Finding the IP Manually
If the hostname doesn't work, you can scan for the Pi.

1.  Run `arp -a` in the terminal.
2.  Look for an interface with an IP like `169.254.x.x` (Auto-IP) or `192.168.137.x` (if using ICS).
3.  The Raspberry Pi's MAC address usually starts with `b8:27:eb` or `dc:a6:32` or `e4:5f:01`.

## Troubleshooting
*   **Lights**: Ensure the Ethernet port LEDs on the Pi are blinking.
*   **Firewall**: Sometimes Windows Firewall blocks mDNS. Try disabling it temporarily if you can't ping `raspberrypi.local`.
*   **SSH Enabled?**: Ensure SSH was enabled in `raspi-config` or by placing an empty file named `ssh` in the `/boot/` partition of the SD card.
