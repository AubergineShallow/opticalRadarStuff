"""
websocket_server.py
PURPOSE: Broadcast server state to frontend via WebSockets.
"""

import asyncio
import json
import threading
import websockets
from typing import Dict, List, Optional
import time

class WebSocketBroadcaster:
    """
    Broadcasts state updates to connected WebSocket clients.
    """
    
    def __init__(self, port: int = 5000):
        self.port = port
        self.clients = set()
        self.loop = None
        self.thread = None
        self.running = False
        self._stop_event: Optional[asyncio.Event] = None
        
    def start(self):
        """Start the WebSocket server in a separate thread."""
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f"WebSocket server started on port {self.port}")

    def stop(self):
        """Stop the WebSocket server cleanly."""
        self.running = False
        # Signal the asyncio event loop to stop
        if self.loop and self._stop_event:
            self.loop.call_soon_threadsafe(self._stop_event.set)
        if self.thread:
            self.thread.join(timeout=2.0)
        
    def _run_loop(self):
        """Run the asyncio loop."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._stop_event = asyncio.Event()
        
        try:
            self.loop.run_until_complete(self._serve_forever())
        except Exception as e:
            print(f"WebSocket loop error: {e}")
        finally:
            self.loop.close()
            
    async def _serve_forever(self):
        """Run server until stop event is set."""
        try:
            async with websockets.serve(self._handler, "0.0.0.0", self.port):
                print(f"WebSocket server running on port {self.port}")
                await self._stop_event.wait()  # Blocks until stop() signals
        except Exception as e:
            print(f"WebSocket startup check failed: {e}")

    async def _handler(self, websocket): # Removed path argument for compatibility with newer websockets
        """Handle new connection."""
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.remove(websocket)
            
    def broadcast(self, message_type: str, data: any):
        """
        Broadcast a message to all clients.
        
        Args:
            message_type: 'NODE_UPDATE', 'TRACK_UPDATE', 'SYSTEM_STATUS'
            data: JSON-serializable data payload
        """
        if not self.loop or not self.clients:
            return
            
        payload = json.dumps({
            "type": message_type,
            "timestamp": time.time(),
            "payload": data
        })
        
        # Scheduling the broadcast in the event loop
        asyncio.run_coroutine_threadsafe(self._broadcast_async(payload), self.loop)
        
    async def _broadcast_async(self, payload: str):
        """Async broadcast."""
        if not self.clients:
            return
            
        # Create list to avoid runtime error if set changes during iteration
        for client in list(self.clients):
            try:
                await client.send(payload)
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                print(f"WS Send Error: {e}")
