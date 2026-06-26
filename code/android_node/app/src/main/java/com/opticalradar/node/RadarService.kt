package com.opticalradar.node

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.IBinder
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.core.app.NotificationCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.concurrent.Executors
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle

/**
 * Foreground service that owns the camera + ML Kit pipeline and sends
 * V3-compatible UDP packets to the OpticalRadar server.
 *
 * The camera is bound to the service's own [LifecycleOwner], so detection
 * continues even when the Activity is stopped or the screen is off.
 *
 * [MainActivity] binds to this service and borrows its [Preview] use case
 * to show a live thumbnail when visible — it does NOT own the camera.
 */
class RadarService : Service(), LifecycleOwner {

    // --- Lifecycle -----------------------------------------------------------
    private val lifecycleRegistry = LifecycleRegistry(this)
    override val lifecycle: Lifecycle get() = lifecycleRegistry

    // --- Coroutines ----------------------------------------------------------
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    // --- Networking ----------------------------------------------------------
    private var udpClient: UdpClient? = null
    private var announceJob: Job? = null

    // --- Camera ID & sequence counter ----------------------------------------
    private var cameraId: String = "android_01"
    private var sequenceNumber: Int = 0

    // --- Real Sensor values ------------------
    private var currentLat: Double = 0.0
    private var currentLon: Double = 0.0
    private var currentAlt: Float = 0.0f
    private var orientation: FloatArray = floatArrayOf(1.0f, 0.0f, 0.0f, 0.0f)

    private var locationManager: LocationManager? = null
    private var sensorManager: SensorManager? = null
    private var rotationVectorSensor: Sensor? = null

    private var lastLocationTimeMs: Long = 0
    private var hasImuData: Boolean = false

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            currentLat = location.latitude
            currentLon = location.longitude
            currentAlt = location.altitude.toFloat()
            lastLocationTimeMs = System.currentTimeMillis()
        }
        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        override fun onProviderEnabled(provider: String) {}
        override fun onProviderDisabled(provider: String) {}
    }

    private val sensorEventListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            if (event.sensor.type == Sensor.TYPE_ROTATION_VECTOR) {
                // Get quaternion from rotation vector
                // The Android rotation vector is defined as [x, y, z, w(optional)] where w = cos(theta/2).
                // Android's SensorManager.getQuaternionFromVector outputs [w, x, y, z]
                val q = FloatArray(4)
                SensorManager.getQuaternionFromVector(q, event.values)

                // Python's ray_builder assumes a specific ENU convention.
                // We'll pass the w,x,y,z directly, matching the rpi_node's layout.
                orientation[0] = q[0] // w
                orientation[1] = q[1] // x
                orientation[2] = q[2] // y
                orientation[3] = q[3] // z
                hasImuData = true
            }
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
    }

    // --- Camera use cases exposed to the activity ----------------------------
    var preview: Preview? = null
        private set

    // --- Observable stats for UI (Phase 3) -----------------------------------
    private val _tracksFound = MutableStateFlow(0)
    val tracksFound: StateFlow<Int> = _tracksFound

    private val _packetsSent = MutableStateFlow(0)
    val packetsSent: StateFlow<Int> = _packetsSent

    // --- Binder --------------------------------------------------------------
    inner class RadarBinder : Binder() {
        fun getService(): RadarService = this@RadarService
    }

    private val binder = RadarBinder()

    override fun onBind(intent: Intent?): IBinder = binder

    // =========================================================================
    // Lifecycle
    // =========================================================================

    override fun onCreate() {
        super.onCreate()
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val serverIp = intent?.getStringExtra("SERVER_IP") ?: "127.0.0.1"
        val serverPort = intent?.getIntExtra("SERVER_PORT", 5005) ?: 5005
        cameraId = intent?.getStringExtra("CAMERA_ID") ?: "android_01"

        // Guard against re-entrant starts — close any old socket first
        udpClient?.close()
        udpClient = null
        announceJob?.cancel()

        createNotificationChannel()
        // Camera must open *after* startForeground() — Android 14's FGS
        // type-start ordering requires this for the `camera` type.
        startForeground(1, buildNotification("Radar Node Active. ID: $cameraId"))

        // Drive lifecycle to RESUMED so CameraX will open the camera
        if (lifecycleRegistry.currentState.isAtLeast(Lifecycle.State.CREATED) &&
            !lifecycleRegistry.currentState.isAtLeast(Lifecycle.State.RESUMED)
        ) {
            lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_START)
            lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_RESUME)
        }

        // Initialize sensors
        initSensors()

        // Initialise camera + analysis pipeline
        initCameraAndAnalysis()

        // Initialise UDP client off the main thread (InetAddress.getByName does DNS)
        scope.launch {
            try {
                udpClient = UdpClient(serverIp, serverPort)

                // Re-announce every 5 s (matching rpi_node.py convention).
                // A single announce lost on a flaky network leaves the node
                // stuck unassigned in the server's cluster_manager.
                announceJob = launch {
                    while (isActive) {
                        try {
                            val ts = System.currentTimeMillis().toDouble() / 1000.0
                            udpClient?.sendAnnounce(
                                cameraId = cameraId,
                                timestamp = ts,
                                fovH = 60.0f,
                                fovV = 45.0f,
                                resW = 640,
                                resH = 480,
                                fps = 30
                            )
                        } catch (e: Exception) {
                            e.printStackTrace()
                        }
                        delay(5000)
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }

        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()

        // Tear down lifecycle — CameraX will unbind automatically
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_PAUSE)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_STOP)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY)

        scope.cancel()
        udpClient?.close()
        udpClient = null

        try {
            locationManager?.removeUpdates(locationListener)
            sensorManager?.unregisterListener(sensorEventListener)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    // =========================================================================
    // Camera + ML Kit
    // =========================================================================

    /**
     * Opens the camera and binds Preview + ImageAnalysis to this service's
     * lifecycle.  Detection runs regardless of whether any Activity is bound.
     */
    private fun initCameraAndAnalysis() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)

        cameraProviderFuture.addListener({
            val provider = cameraProviderFuture.get()
            provider.unbindAll()

            // Preview — the Activity can attach its SurfaceProvider later
            preview = Preview.Builder().build()

            // ImageAnalysis — feeds frames to VisionAnalyzer
            val imageAnalysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()

            imageAnalysis.setAnalyzer(
                Executors.newSingleThreadExecutor(),
                VisionAnalyzer(60.0f, 45.0f) { tracks ->
                    onDetectionsReceived(tracks)
                }
            )

            try {
                provider.bindToLifecycle(
                    this,  // RadarService implements LifecycleOwner
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    imageAnalysis
                )
            } catch (exc: Exception) {
                exc.printStackTrace()
            }
        }, ContextCompat.getMainExecutor(this))
    }

    // =========================================================================
    // Detection callback
    // =========================================================================

    /**
     * Called by [VisionAnalyzer] whenever a new batch of tracked objects is
     * available.  Packs them into a single V3 Telemetry packet and sends it.
     */
    private fun onDetectionsReceived(tracks: List<TrackedObject>) {
        _tracksFound.value += tracks.size

        scope.launch {
            try {
                val ts = System.currentTimeMillis().toDouble() / 1000.0

                udpClient?.sendTelemetry(
                    cameraId = cameraId,
                    sequenceNumber = sequenceNumber++ and 0x7FFFFFFF,
                    timestamp = ts,
                    latitude = currentLat,
                    longitude = currentLon,
                    altitude = currentAlt,
                    orientation = orientation,
                    healthFlags = computeHealthFlags(),
                    tracks = tracks
                )
                _packetsSent.value += 1
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    private fun computeHealthFlags(): Byte {
        var flags = 0
        // CAMERA_OK (bit 1)
        if (preview != null) flags = flags or 0x02

        // GPS_OK (bit 0) - valid if less than 10 seconds old
        val now = System.currentTimeMillis()
        if (lastLocationTimeMs > 0 && (now - lastLocationTimeMs) < 10000) {
            flags = flags or 0x01
        }

        // IMU_OK (bit 2)
        if (hasImuData) flags = flags or 0x04

        return flags.toByte()
    }
    // =========================================================================
    // Notification plumbing
    // =========================================================================

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            "RADAR_CHANNEL", "Radar Service", NotificationManager.IMPORTANCE_LOW
        )
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
