"""
websocket_server.py
PURPOSE: Broadcast server state to frontend via WebSockets.

Implements (P0.6 / Integration Plan A):
  - Per-cluster "rooms" so a client only receives its domain's tracks.
  - A command-handler registry so the frontend can drive the backend
    (CREATE_CLUSTER, ASSIGN_NODE, SUBSCRIBE_CLUSTER).
  - Thin broadcast_* wrappers that thread an optional `room` through.

Message contract (server -> client):
  { "type": <TYPE>, "timestamp": <float>, "payload": <data> }
  TYPE in {TRACK_UPDATE, NODE_UPDATE, SYSTEM_STATUS, VOXEL_UPDATE, RAY_UPDATE,
           CLUSTER_UPDATE}

Command contract (client -> server):
  { "type": <COMMAND>, "payload": { ... } }
  COMMAND in {SUBSCRIBE_CLUSTER, CREATE_CLUSTER, ASSIGN_NODE}
"""

import asyncio
import json
import threading
import websockets
from collections import defaultdict
from typing import Dict, List, Optional, Set, Callable, Any
import time


class WebSocketBroadcaster:
    """
    Broadcasts state updates to connected WebSocket clients.

    Runs an asyncio event loop on a dedicated daemon thread. All public
    broadcast_* methods are safe to call from the main (synchronous) server
    loop; they schedule the actual send onto the asyncio loop.
    """

    def __init__(self, port: int = 5000):
        self.port = port
        self.clients: Set = set()
        # cluster_id -> set of subscribed websockets
        self._rooms: Dict[str, Set] = defaultdict(set)
        # command name -> handler(client_id, payload)
        self._command_handlers: Dict[str, Callable[[str, dict], Any]] = {}
        self.loop = None
        self.thread = None
        self.running = False

    # ------------------------------------------------------------------ #
    # Command registry                                                   #
    # ------------------------------------------------------------------ #
    def register_command_handler(
        self, command: str, handler: Callable[[str, dict], Any]
    ) -> None:
        """Register a handler for an inbound command type."""
        self._command_handlers[command] = handler

    # ------------------------------------------------------------------ #
    # Room subscription                                                  #
    # ------------------------------------------------------------------ #
    def subscribe(self, websocket, cluster_id: str) -> None:
        """Subscribe a client to a cluster room (one active room per client)."""
        for room in self._rooms.values():
            room.discard(websocket)
        self._rooms[cluster_id].add(websocket)

    def unsubscribe(self, websocket) -> None:
        """Remove a client from every room."""
        for room in self._rooms.values():
            room.discard(websocket)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #
    def start(self):
        """Start the WebSocket server in a separate thread."""
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f"WebSocket server started on port {self.port}")

    def stop(self):
        """Stop the WebSocket server."""
        self.running = False
        # Daemon thread; loop is torn down on process exit.

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

    async def _handler(self, websocket):  # No `path` arg: newer websockets API
        """Handle a connection: register, pump inbound commands, clean up."""
        self.clients.add(websocket)
        try:
            async for raw_message in websocket:
                await self._on_message(websocket, raw_message)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"WS handler error: {e}")
        finally:
            self.clients.discard(websocket)
            self.unsubscribe(websocket)

    async def _on_message(self, websocket, raw_message: str):
        """Dispatch an inbound client message."""
        try:
            msg = json.loads(raw_message)
        except (ValueError, TypeError):
            return

        command = msg.get("type")
        payload = msg.get("payload", {}) or {}

        if command == "SUBSCRIBE_CLUSTER":
            cluster_id = payload.get("cluster_id")
            if cluster_id:
                self.subscribe(websocket, cluster_id)
            return

        handler = self._command_handlers.get(command)
        if handler is None:
            return

        client_id = str(id(websocket))
        try:
            result = handler(client_id, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            print(f"WS command handler error ({command}): {e}")

    # ------------------------------------------------------------------ #
    # Outbound broadcast                                                 #
    # ------------------------------------------------------------------ #
    def broadcast(self, message_type: str, data: Any, room: Optional[str] = None):
        """
        Broadcast a message to all clients, or only to a cluster room.

        Args:
            message_type: e.g. 'NODE_UPDATE', 'TRACK_UPDATE', 'SYSTEM_STATUS'
            data: JSON-serializable payload
            room: if set, only deliver to clients subscribed to this cluster
        """
        if not self.loop:
            return

        payload = json.dumps({
            "type": message_type,
            "timestamp": time.time(),
            "payload": data
        })

        # Schedule the send on the event loop thread; the room->target lookup
        # happens there to avoid cross-thread races on `_rooms`/`clients`.
        asyncio.run_coroutine_threadsafe(
            self._broadcast_async(payload, room), self.loop
        )

    async def _broadcast_async(self, payload: str, room: Optional[str]):
        """Async broadcast to the resolved set of targets."""
        if room is not None:
            targets = list(self._rooms.get(room, ()))
        else:
            targets = list(self.clients)

        if not targets:
            return

        for client in targets:
            try:
                await client.send(payload)
            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as e:
                print(f"WS Send Error: {e}")

    # ------------------------------------------------------------------ #
    # Typed wrappers (used by server_main)                               #
    # ------------------------------------------------------------------ #
    def broadcast_tracks(self, tracks, room: Optional[str] = None):
        """Tracks are room-scoped: a client only sees its subscribed cluster."""
        self.broadcast("TRACK_UPDATE", tracks, room=room)

    def broadcast_node_update(self, node_data, room: Optional[str] = None):
        """Node updates are global by default (frontend filters by cluster_id)."""
        self.broadcast("NODE_UPDATE", node_data, room=room)

    def broadcast_voxels(self, voxels, room: Optional[str] = None):
        """Hot-voxel heatmap for a cluster (room-scoped)."""
        self.broadcast("VOXEL_UPDATE", voxels, room=room)

    def broadcast_rays(self, rays, room: Optional[str] = None):
        """Per-frame sensor rays for a cluster (room-scoped)."""
        self.broadcast("RAY_UPDATE", rays, room=room)

    def broadcast_system_status(self, status: dict):
        """System status spans all clusters; always global."""
        self.broadcast("SYSTEM_STATUS", status)

    def broadcast_clusters(self, clusters: dict):
        """Cluster topology update (drives the frontend domain dropdown)."""
        self.broadcast("CLUSTER_UPDATE", clusters)
