"""
websocket_server.py
PURPOSE: Broadcast server state to frontend via WebSockets.
"""

import asyncio
import json
import threading
import websockets
from typing import Dict, List, Optional, Callable, Any
import time
from collections import defaultdict

class WebSocketBroadcaster:
    """
    Broadcasts state updates to connected WebSocket clients.
    """
    
    def __init__(self, port: int = 5000):
        self.port = port
        self.clients = set()
        self._rooms: Dict[str, set] = defaultdict(set)
        self._command_handlers: Dict[str, Callable[[dict], Any]] = {}
        self.loop = None
        self.thread = None
        self.running = False
        
    def start(self):
        """Start the WebSocket server in a separate thread."""
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f"WebSocket server started on port {self.port}")

    def stop(self):
        """Stop the WebSocket server."""
        self.running = False
        # Ideally we would signal the loop to stop, but for daemon thread simple join/ignore is common in simple scripts
        # Proper asyncio cleanup is tricky across threads without a dedicated signal
        
    def _run_loop(self):
        """Run the asyncio loop."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            self.loop.run_until_complete(self._serve_forever())
        except Exception as e:
            print(f"WebSocket loop error: {e}")
        finally:
            self.loop.close()
            
    async def _serve_forever(self):
        """Run server using async context manager."""
        try:
            async with websockets.serve(self._handler, "0.0.0.0", self.port):
                print(f"WebSocket server running on port {self.port}")
                await asyncio.Future()  # Run forever
        except Exception as e:
            print(f"WebSocket startup check failed: {e}")

    async def _handler(self, websocket):
        """Handle new connection and process inbound messages."""
        self.clients.add(websocket)
        try:
            async for raw_message in websocket:
                await self._on_message(websocket, raw_message)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"WS Handler Error: {e}")
        finally:
            self.clients.remove(websocket)
            for room in self._rooms.values():
                room.discard(websocket)
    def register_command_handler(self, command: str, handler: Callable[[dict], Any]):
        """Register a callback for an inbound message command."""
        self._command_handlers[command] = handler

    def subscribe(self, websocket, cluster_id: str):
        """Subscribe a websocket to a specific cluster room."""
        # One active subscription per client
        for room in self._rooms.values():
            room.discard(websocket)
        self._rooms[cluster_id].add(websocket)

    async def _on_message(self, websocket, raw_message: str):
        try:
            msg = json.loads(raw_message)
            command = msg.get("type")
            if command == "SUBSCRIBE_CLUSTER":
                self.subscribe(websocket, msg["payload"]["cluster_id"])
                return
            
            handler = self._command_handlers.get(command)
            if handler:
                if asyncio.iscoroutinefunction(handler):
                    await handler(msg.get("payload", {}))
                else:
                    handler(msg.get("payload", {}))
        except json.JSONDecodeError:
            print("Received invalid JSON on websocket")
        except Exception as e:
            print(f"Error handling websocket message: {e}")

    def broadcast(self, message_type: str, data: any, room: Optional[str] = None):
        """
        Broadcast a message to clients. If room is specified, only broadcast to clients in that room.
        """
        if not self.loop or not self.clients:
            return
            
        targets = self._rooms.get(room, set()) if room else self.clients
        if not targets:
            return

        payload = json.dumps({
            "type": message_type,
            "timestamp": time.time(),
            "payload": data
        })
        
        asyncio.run_coroutine_threadsafe(self._broadcast_async(payload, targets), self.loop)

    async def _broadcast_async(self, payload: str, targets: set):
        """Async broadcast."""
        for client in list(targets):
            try:
                await client.send(payload)
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                print(f"WS Send Error: {e}")

    def broadcast_tracks(self, tracks, room=None):
        self.broadcast("TRACK_UPDATE", tracks, room=room)

    def broadcast_node_update(self, node_data, room=None):
        self.broadcast("NODE_UPDATE", node_data, room=room)

    def broadcast_system_status(self, status: dict):
        self.broadcast("SYSTEM_STATUS", status)