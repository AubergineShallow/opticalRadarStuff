
import subprocess
import sys
import time

def run_ssh(command, password="123456789"):
    # Using python to handle some of the interaction or just wrapping the command
    # On Windows, we can use 'pscp' or 'plink' if available, but 'ssh' is usually there now.
    # However, 'ssh' doesn't take password on command line.
    
    # We'll try to use a heredoc or similar if possible, but the best way without extra dependencies
    # is often a small script that uses something like 'expect' or just 'paramiko'.
    # Since I don't know what's installed, let's try to check for 'sshpass' first or use a simple method.
    
    # Actually, I'll attempt to run it and see if it works with an interactive-like approach if I had one.
    # Since I don't, I'll try to use 'plink' (from PuTTY) if it exists, or just tell the user I'm trying.
    
    full_cmd = f"ssh pi@raspberrypi.local {command}"
    print(f"Running: {full_cmd}")
    # This will likely fail to provide password.
    
    # Let's try to use a python script with 'paramiko' if available. 
    # If not, I'll try to find another way.
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect('169.254.212.49', username='pi', password=password, timeout=10)
        stdin, stdout, stderr = client.exec_command(command)
        print(stdout.read().decode())
        print(stderr.read().decode())
        client.close()
    except ImportError:
        print("Paramiko not installed. Falling back to subprocess (may fail for password).")
        # Fallback... 
        pass
    except Exception as e:
        print(f"Error: {e}")

def upload_file(local_path, remote_path, password="123456789"):
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect('169.254.212.49', username='pi', password=password, timeout=10)
        sftp = client.open_sftp()
        print(f"Uploading {local_path} to {remote_path}")
        sftp.put(local_path, remote_path)
        sftp.close()
        client.close()
        print("Upload complete.")
    except Exception as e:
        print(f"Upload failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "upload":
        upload_file(sys.argv[2], sys.argv[3])
    elif len(sys.argv) > 1:
        run_ssh(sys.argv[1])
    else:
        run_ssh("ps aux | grep python")
