package com.opticalradar.node

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Handles sending the highly compressed binary TelemetryPacket to the Python server.
 */
class UdpClient(private val serverIp: String, private val serverPort: Int) {
    private val socket = DatagramSocket()
    private val address = InetAddress.getByName(serverIp)

    /**
     * Sends the Announce packet. Matches the Python `LoraAnnouncePacket` C-struct.
     * [uint8 type][uint8 node_id][float32 lat][float32 lon][float32 alt][int16 roll][int16 pitch][int16 yaw]
     */
    fun sendAnnounce(nodeId: Int, lat: Float, lon: Float, alt: Float, roll: Float, pitch: Float, yaw: Float) {
        val buffer = ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put(0x01.toByte()) // MSG_TYPE_ANNOUNCE
        buffer.put(nodeId.toByte())
        buffer.putFloat(lat)
        buffer.putFloat(lon)
        buffer.putFloat(alt)
        buffer.putShort((roll * 100).toInt().toShort())
        buffer.putShort((pitch * 100).toInt().toShort())
        buffer.putShort((yaw * 100).toInt().toShort())

        val packet = DatagramPacket(buffer.array(), buffer.capacity(), address, serverPort)
        socket.send(packet)
    }

    /**
     * Sends the Update packet. Matches the Python `LoraUpdatePacket` C-struct.
     * [uint8 type][uint8 node_id][uint8 track_id][uint16 az][int8 el]
     */
    fun sendUpdate(nodeId: Int, trackId: Int, azimuth: Float, elevation: Float) {
        val buffer = ByteBuffer.allocate(6).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put(0x02.toByte()) // MSG_TYPE_UPDATE
        buffer.put(nodeId.toByte())
        buffer.put(trackId.toByte())

        val azComp = ((azimuth / 360.0) * 65535).toInt()
        buffer.putShort(azComp.toShort())

        // Clamp elevation between -128 and 127
        val elComp = elevation.toInt().coerceIn(-128, 127)
        buffer.put(elComp.toByte())

        val packet = DatagramPacket(buffer.array(), buffer.capacity(), address, serverPort)
        socket.send(packet)
    }

    fun close() {
        socket.close()
    }
}
