import multiprocessing
import time
import sys
import os

# Ensure code directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.server_main import OpticalRadarServer
from simulation.sim_node import create_demo_simulation

def run_server():
    print("[Launcher] Starting Server...")
    server = OpticalRadarServer(headless=True) # Run headless, UI connects via WS
    server.run()

def run_simulation():
    # Give server time to start
    time.sleep(2)
    print("[Launcher] Starting Simulation Nodes...")
    nodes = create_demo_simulation(num_cameras=4, num_targets=3, arena_size=150.0)
    
    # Start all nodes
    for node in nodes:
        node.start()
        
    print(f"[Launcher] Running {len(nodes)} simulation nodes...")
    
    try:
        # Run loop
        start_time = time.time()
        while True:
            frame_start = time.time()
            dt = 0.1 # 10 FPS for sim
            
            for node in nodes:
                node.update_targets(dt)
                node.process_frame()
                
            elapsed = time.time() - frame_start
            if elapsed < dt:
                time.sleep(dt - elapsed)
                
            if time.time() - start_time > 60: # Run for 60 seconds then exit
                break
    except KeyboardInterrupt:
        pass
    finally:
        for node in nodes:
            node.stop()
        print("[Launcher] Simulation stopped.")

if __name__ == "__main__":
    # Start server process
    p_server = multiprocessing.Process(target=run_server)
    p_server.start()
    
    # Run simulation in main process (or another process)
    try:
        run_simulation()
    except KeyboardInterrupt:
        pass
    finally:
        p_server.terminate()
        p_server.join()
