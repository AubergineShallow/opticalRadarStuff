package com.opticalradar.node

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.*
import kotlin.math.asin
import kotlin.math.atan2

class RadarService : Service() {
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var udpClient: UdpClient? = null

    // In a full implementation, these would be polled from Android's LocationManager and SensorManager
    private var currentLat = 0.0f
    private var currentLon = 0.0f
    private var currentAlt = 0.0f
    private var roll = 0.0f
    private var pitch = 0.0f
    private var yaw = 0.0f

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val serverIp = intent?.getStringExtra("SERVER_IP") ?: "127.0.0.1"
        val serverPort = intent?.getIntExtra("SERVER_PORT", 5005) ?: 5005
        val nodeId = intent?.getIntExtra("NODE_ID", 1) ?: 1

        udpClient = UdpClient(serverIp, serverPort)

        createNotificationChannel()
        startForeground(1, buildNotification("Radar Node Active. Node ID: $nodeId"))

        // Send Boot Announce
        scope.launch {
            udpClient?.sendAnnounce(nodeId, currentLat, currentLon, currentAlt, roll, pitch, yaw)
        }

        // Note: In reality, CameraX lifecycle is heavily tied to Activities or ProcessCameraProvider.
        // Starting a camera directly inside a Service without a LifecycleOwner requires a custom LifecycleRegistry.
        // We abstract the VisionAnalyzer hook here.

        return START_STICKY
    }

    // Called by the VisionAnalyzer (which would be bound to the Service's custom Lifecycle)
    fun onDetectionsReceived(nodeId: Int, tracks: List<TrackedObject>) {
        scope.launch {
            for (track in tracks) {
                // Send the UDP packet over the network
                udpClient?.sendUpdate(nodeId, track.trackId, track.azimuth, track.elevation, track.angularSize)
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
        udpClient?.close()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        val channel = NotificationChannel("RADAR_CHANNEL", "Radar Service", NotificationManager.IMPORTANCE_LOW)
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification {
        return NotificationCompat.Builder(this, "RADAR_CHANNEL")
            .setContentTitle("Optical Radar")
            .setContentText(text)
            .setOngoing(true)
            .build()
    }
}
