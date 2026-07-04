package com.opticalradar.node

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Sends V3-compatible binary packets to the Python OpticalRadar server.
 *
 * All packets use big-endian byte order to match the server's struct.unpack('>')
 * format strings in common/protocol.py.
 */
class UdpClient(private val serverIp: String, private val serverPort: Int) {
    private val socket = DatagramSocket()
    private val address = InetAddress.getByName(serverIp)

    /**
     * Sends a V3 Announce packet (31 bytes).
     *
     * Layout (big-endian):
     *   B  version          (1)
     *   B  packet_type=0x04 (1)
     *   8s camera_id        (8, UTF-8 null-padded)
     *   d  timestamp        (8)
     *   f  fov_horizontal   (4)
     *   f  fov_vertical     (4)
     *   H  resolution_w     (2)
     *   H  resolution_h     (2)
     *   B  fps              (1)
     *                       -----
     *                       31 bytes
     */
    fun sendAnnounce(
        cameraId: String,
        timestamp: Double,
        fovH: Float,
        fovV: Float,
        resW: Int,
        resH: Int,
        fps: Int
    ) {
        val buffer = ByteBuffer.allocate(31).order(ByteOrder.BIG_ENDIAN)

        // Header
        buffer.put(0x03.toByte())  // VERSION = 3
        buffer.put(0x04.toByte())  // PACKET_TYPE_ANNOUNCE

        // Camera ID: 8 bytes, UTF-8, null-padded
        val camIdBytes = ByteArray(8)
        val utf8 = cameraId.toByteArray(Charsets.UTF_8)
        System.arraycopy(utf8, 0, camIdBytes, 0, minOf(utf8.size, 8))
        buffer.put(camIdBytes)

        buffer.putDouble(timestamp)

        // Payload
        buffer.putFloat(fovH)
        buffer.putFloat(fovV)
        buffer.putShort(resW.toShort())
        buffer.putShort(resH.toShort())
        buffer.put(fps.toByte())

        val packet = DatagramPacket(buffer.array(), buffer.capacity(), address, serverPort)
        socket.send(packet)
    }

    /**
     * Sends a V3 Telemetry packet (61-byte header + N × 8-byte motion vectors).
     *
     * Header layout (big-endian, 61 bytes):
     *   B  version            (1)
     *   B  packet_type=0x01   (1)
     *   8s camera_id          (8)
     *   I  sequence_number    (4)
     *   d  timestamp          (8)
     *   d  latitude           (8)
     *   d  longitude          (8)
     *   f  altitude           (4)
     *   f  qw                 (4)
     *   f  qx                 (4)
     *   f  qy                 (4)
     *   f  qz                 (4)
     *   B  health_flags       (1)
     *   H  vector_count       (2)
     *                         -----
     *                         61 bytes
     *
     * Per-vector layout (big-endian, 8 bytes):
     *   H  az_raw             (2)  azimuth  [0,360) → [0,65535]
     *   h  el_raw             (2)  elevation [-90,90] → [-32768,32767]
     *   B  intensity          (1)  [0,255]
     *   B  class_id           (1)  [0,255]
     *   H  size_raw           (2)  angular_size [0,180] → [0,65535]
     */
    fun sendTelemetry(
        cameraId: String,
        sequenceNumber: Int,
        timestamp: Double,
        latitude: Double,
        longitude: Double,
        altitude: Float,
        orientation: FloatArray,   // [w, x, y, z]
        healthFlags: Byte,
        tracks: List<TrackedObject>
    ) {
        val vectorCount = tracks.size
        val totalSize = 61 + vectorCount * 8
        val buffer = ByteBuffer.allocate(totalSize).order(ByteOrder.BIG_ENDIAN)

        // --- Header (61 bytes) ---
        buffer.put(0x03.toByte())  // VERSION = 3
        buffer.put(0x01.toByte())  // PACKET_TYPE_TELEMETRY

        val camIdBytes = ByteArray(8)
        val utf8 = cameraId.toByteArray(Charsets.UTF_8)
        System.arraycopy(utf8, 0, camIdBytes, 0, minOf(utf8.size, 8))
        buffer.put(camIdBytes)

        buffer.putInt(sequenceNumber)
        buffer.putDouble(timestamp)
        buffer.putDouble(latitude)
        buffer.putDouble(longitude)
        buffer.putFloat(altitude)

        // Orientation quaternion [w, x, y, z]
        buffer.putFloat(orientation[0])
        buffer.putFloat(orientation[1])
        buffer.putFloat(orientation[2])
        buffer.putFloat(orientation[3])

        buffer.put(healthFlags)
        buffer.putShort((vectorCount and 0xFFFF).toShort())

        // --- Motion Vectors (N × 8 bytes) ---
        for (track in tracks) {
            // Azimuth: explicit mod-360 normalisation to handle negative boresight-centered
            // values from VisionAnalyzer (roughly −30°..+30°).  An unsigned uint16 field
            // needs a real [0, 360) mapping, not an incidental two's-complement trick.
            val azNorm = ((track.azimuth % 360f) + 360f) % 360f
            val azRaw = (azNorm / 360f * 65535f).toInt() and 0xFFFF

            // Elevation: signed int16
            val elRaw = (track.elevation / 90f * 32767f).toInt().coerceIn(-32768, 32767)

            // Angular size: unsigned uint16 — note /180*65535, NOT the old LoRa /180*255
            val sizeRaw = (track.angularSize / 180f * 65535f).toInt().coerceIn(0, 65535)

            buffer.putShort(azRaw.toShort())
            buffer.putShort(elRaw.toShort())
            buffer.put((track.intensity and 0xFF).toByte())
            buffer.put((track.classId and 0xFF).toByte())
            buffer.putShort(sizeRaw.toShort())
        }

        val packet = DatagramPacket(buffer.array(), buffer.capacity(), address, serverPort)
        socket.send(packet)
    }

    fun close() {
        socket.close()
    }
}
