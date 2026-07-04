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
        # Completed (from the loop thread) to make _serve_forever return,
        # which tears the server down and unbinds the port.
        self._stop_future = None

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
        """Subscribe a client to a cluster room (one active room per client).

        Removing the client from its previous room first (which prunes that room
        if it empties) bounds `_rooms` to at most the number of connected
        clients: a client that names 1000 distinct cluster_ids leaves no trail of
        empty room sets behind it.
        """
        self.unsubscribe(websocket)
        self._rooms[cluster_id].add(websocket)

    def unsubscribe(self, websocket) -> None:
        """Remove a client from every room, pruning any room left empty."""
        emptied = []
        for cluster_id, room in self._rooms.items():
            room.discard(websocket)
            if not room:
                emptied.append(cluster_id)
        for cluster_id in emptied:
            del self._rooms[cluster_id]

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
        """Stop the WebSocket server: unbind the port and join the loop thread.

        The old implementation only flipped a flag, so the port stayed bound
        forever (an in-process restart could never re-bind) and the event loop
        thread kept running.
        """
        self.running = False

        thread = self.thread
        if thread is None:
            return

        # The loop/future are created on the loop thread; if stop() races a
        # just-started thread, give them a moment to appear.
        deadline = time.time() + 1.0
        while (self._stop_future is None and thread.is_alive()
               and time.time() < deadline):
            time.sleep(0.01)

        loop, stop_future = self.loop, self._stop_future
        if loop is not None and stop_future is not None:
            def _signal():
                if not stop_future.done():
                    stop_future.set_result(None)
            try:
                loop.call_soon_threadsafe(_signal)
            except RuntimeError:
                pass  # loop already closed

        thread.join(timeout=2.0)
        self.thread = None

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
        """Run server until stop() completes the stop future."""
        self._stop_future = asyncio.get_running_loop().create_future()
        try:
            async with websockets.serve(self._handler, "0.0.0.0", self.port):
                print(f"WebSocket server running on port {self.port}")
                await self._stop_future
        except Exception as e:
            # Surface bind/startup failures loudly: the server otherwise keeps
            # running with no UI channel at all.
            print(f"ERROR: WebSocket server failed on port {self.port}: {e}")
            self.running = False

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

        # A client can send any well-formed JSON — an array, number, string or
        # null are all valid JSON but have no .get(). Treating them as a command
        # object raised AttributeError, which propagated up to _handler and tore
        # down the client's connection. Ignore any non-object frame instead.
        if not isinstance(msg, dict):
            return

        command = msg.get("type")
        payload = msg.get("payload") or {}
        # payload must be an object for the handlers that index into it; a client
        # sending "payload": [1,2] or a bare scalar must not crash the dispatch.
        if not isinstance(payload, dict):
            payload = {}

        if command == "SUBSCRIBE_CLUSTER":
            cluster_id = payload.get("cluster_id")
            # Room keys must be hashable strings; a client sending a dict/list
            # cluster_id would otherwise raise (unhashable) inside subscribe().
            if isinstance(cluster_id, str) and cluster_id:
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
        if not self.loop or not self.running:
            return

        payload = json.dumps({
            "type": message_type,
            "timestamp": time.time(),
            "payload": data
        })

        # Schedule the send on the event loop thread; the room->target lookup
        # happens there to avoid cross-thread races on `_rooms`/`clients`.
        try:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_async(payload, room), self.loop
            )
        except RuntimeError:
            pass  # loop shut down between the check and the call

    async def _broadcast_async(self, payload: str, room: Optional[str]):
        """Async broadcast to the resolved set of targets.

        Sends fan out concurrently via asyncio.gather instead of a serial await
        loop, so one slow/backed-up client no longer stalls delivery to every
        other client on the same broadcast (head-of-line blocking). Clients whose
        send fails are pruned so a dead socket doesn't linger in the set.
        """
        if room is not None:
            targets = list(self._rooms.get(room, ()))
        else:
            targets = list(self.clients)

        if not targets:
            return

        results = await asyncio.gather(
            *(client.send(payload) for client in targets),
            return_exceptions=True,
        )

        for client, result in zip(targets, results):
            if isinstance(result, Exception):
                if not isinstance(result, websockets.exceptions.ConnectionClosed):
                    print(f"WS Send Error: {result}")
                # Drop the client from both the global set and every room so a
                # closed/errored socket is not retried on the next broadcast.
                self.clients.discard(client)
                self.unsubscribe(client)

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
