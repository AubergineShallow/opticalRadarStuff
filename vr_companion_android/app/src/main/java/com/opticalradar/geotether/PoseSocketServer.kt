package com.opticalradar.geotether

import android.util.Log
import org.java_websocket.WebSocket
import org.java_websocket.handshake.ClientHandshake
import org.java_websocket.server.WebSocketServer
import java.net.InetSocketAddress
import java.util.Collections

/**
 * Embedded WebSocket server the headset connects to over the tether.
 *
 * One-way feed: the service broadcasts GEO_POSE JSON; inbound messages are
 * ignored. The client set is BOUNDED (MAX_CLIENTS) — a misbehaving network
 * peer can't grow server state (the same every-collection-bounded rule the
 * OpticalRadar server follows).
 */
class PoseSocketServer(
    port: Int,
    private val helloJson: String,
    private val onClientsChanged: (Int) -> Unit,
) : WebSocketServer(InetSocketAddress(port)) {

    companion object {
        private const val TAG = "PoseSocketServer"
        const val MAX_CLIENTS = 4
    }

    private val clients: MutableSet<WebSocket> =
        Collections.synchronizedSet(mutableSetOf())

    override fun onStart() {
        // Ping/pong keepalive so half-open tether sockets get reaped.
        connectionLostTimeout = 30
        Log.i(TAG, "Listening on ${address.port}")
    }

    override fun onOpen(conn: WebSocket, handshake: ClientHandshake) {
        if (clients.size >= MAX_CLIENTS) {
            Log.w(TAG, "Rejecting ${conn.remoteSocketAddress}: client cap reached")
            conn.close(1013, "client limit reached") // 1013 = try again later
            return
        }
        clients.add(conn)
        try {
            conn.send(helloJson)
        } catch (e: Exception) {
            Log.w(TAG, "Hello send failed: ${e.message}")
        }
        Log.i(TAG, "Client connected: ${conn.remoteSocketAddress} (${clients.size})")
        onClientsChanged(clients.size)
    }

    override fun onClose(conn: WebSocket, code: Int, reason: String, remote: Boolean) {
        clients.remove(conn)
        Log.i(TAG, "Client disconnected (${clients.size}): $reason")
        onClientsChanged(clients.size)
    }

    override fun onMessage(conn: WebSocket, message: String) {
        // One-way feed; nothing to handle. Logged at debug for diagnosis only.
        Log.d(TAG, "Ignoring inbound message: ${message.take(64)}")
    }

    override fun onError(conn: WebSocket?, ex: Exception) {
        Log.w(TAG, "Socket error: ${ex.message}")
        if (conn != null) {
            clients.remove(conn)
            onClientsChanged(clients.size)
        }
    }

    /** Broadcast a pose frame to every connected headset (best-effort). */
    fun broadcastPose(json: String) {
        synchronized(clients) {
            for (client in clients) {
                try {
                    if (client.isOpen) client.send(json)
                } catch (e: Exception) {
                    Log.w(TAG, "Send failed: ${e.message}")
                }
            }
        }
    }

    fun clientCount(): Int = clients.size
}
