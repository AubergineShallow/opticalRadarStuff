package com.opticalradar.node

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.concurrent.Executors

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

    // --- Real GPS + IMU state (P1.6) -----------------------------------------
    @Volatile private var currentLat: Double = 0.0
    @Volatile private var currentLon: Double = 0.0
    @Volatile private var currentAlt: Float = 0.0f
    // Orientation quaternion in (w, x, y, z) order, matching the V3 protocol and
    // rpi_node.py's IMU output. Android's ROTATION_VECTOR is referenced to the
    // ENU world frame (X=East, Y=North, Z=Up), same as the server's ray_builder.
    @Volatile private var orientation: FloatArray = floatArrayOf(1.0f, 0.0f, 0.0f, 0.0f)

    // GPS
    private var fusedLocationClient: FusedLocationProviderClient? = null
    private var locationCallback: LocationCallback? = null
    @Volatile private var lastFixElapsedMs: Long = 0L  // SystemClock.elapsedRealtime() of last fix
    @Volatile private var hasGpsFix: Boolean = false

    // IMU
    private var sensorManager: SensorManager? = null
    private var rotationVectorSensor: Sensor? = null
    @Volatile private var imuActive: Boolean = false
    @Volatile private var cameraActive: Boolean = false

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

    private companion object {
        // Health flag bits (match common/constants.py: GPS=bit0, CAM=bit1, IMU=bit2)
        const val GPS_OK = 0x01
        const val CAMERA_OK = 0x02
        const val IMU_OK = 0x04
        // A GPS fix older than this is considered stale and clears the GPS bit.
        const val GPS_MAX_AGE_MS = 5000L
    }

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
        // BUG-001/002: On Android 14+ (API 34), starting a foreground service
        // with the `camera`/`location` type throws SecurityException unless the
        // matching runtime permission is held at the moment startForeground runs.
        // So we declare ONLY the types we actually have permission for, via the
        // 3-arg ServiceCompat.startForeground (the bare 2-arg call inherited the
        // manifest's camera|location and crashed when the user hadn't granted
        // CAMERA yet). Camera must open *after* startForeground() for ordering.
        val fgsType = computeForegroundServiceType()
        ServiceCompat.startForeground(
            this, 1, buildNotification("Radar Node Active. ID: $cameraId"), fgsType
        )

        // Drive lifecycle to RESUMED so CameraX will open the camera
        if (lifecycleRegistry.currentState.isAtLeast(Lifecycle.State.CREATED) &&
            !lifecycleRegistry.currentState.isAtLeast(Lifecycle.State.RESUMED)
        ) {
            lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_START)
            lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_RESUME)
        }

        // Start real GPS + IMU sensors (P1.6)
        startLocationUpdates()
        startOrientationUpdates()

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

        // Stop sensors (P1.6)
        locationCallback?.let { fusedLocationClient?.removeLocationUpdates(it) }
        locationCallback = null
        sensorManager?.unregisterListener(sensorListener)
        imuActive = false
        hasGpsFix = false
        cameraActive = false

        scope.cancel()
        udpClient?.close()
        udpClient = null
    }

    // =========================================================================
    // Camera + ML Kit
    // =========================================================================

    /**
     * Opens the camera and binds Preview + ImageAnalysis to this service's
     * lifecycle.  Detection runs regardless of whether any Activity is bound.
     */
    private fun initCameraAndAnalysis() {
        // BUG-002: never touch CameraX without CAMERA permission. Binding the
        // camera use cases (and the camera-typed foreground service) throws on
        // Android 14 otherwise. Mirrors the guard in startLocationUpdates().
        if (!hasPermission(Manifest.permission.CAMERA)) {
            cameraActive = false
            return
        }

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
                cameraActive = true
            } catch (exc: Exception) {
                cameraActive = false
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
                    healthFlags = computeHealthFlags(), // derived from real listener state
                    tracks = tracks
                )
                _packetsSent.value += 1
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    // =========================================================================
    // GPS + IMU (P1.6)
    // =========================================================================

    /**
     * Begin high-accuracy location updates via the fused provider (~1 Hz).
     * If the runtime permission is missing, the GPS health bit simply stays
     * clear — MainActivity is responsible for requesting ACCESS_FINE_LOCATION.
     */
    @SuppressLint("MissingPermission")
    private fun startLocationUpdates() {
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 1000L)
            .setMinUpdateIntervalMillis(1000L)
            .build()

        locationCallback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                val loc = result.lastLocation ?: return
                currentLat = loc.latitude
                currentLon = loc.longitude
                currentAlt = loc.altitude.toFloat()
                lastFixElapsedMs = SystemClock.elapsedRealtime()
                hasGpsFix = true
            }
        }

        try {
            fusedLocationClient?.requestLocationUpdates(request, locationCallback!!, mainLooper)
        } catch (e: SecurityException) {
            e.printStackTrace()
        }
    }

    /**
     * Register the TYPE_ROTATION_VECTOR sensor, which already fuses
     * accelerometer + magnetometer + gyro on-device. Converted to a (w, x, y, z)
     * quaternion via [SensorManager.getQuaternionFromVector].
     *
     * AXIS-CONVENTION CAVEAT (OQ6): the rotation vector is referenced to the
     * Android ENU world frame. Before trusting field data, bench-test with the
     * phone in a known orientation (flat, facing magnetic north) and confirm the
     * received quaternion matches what ray_builder.py expects — a silent
     * axis/sign mismatch looks like noise, not a crash, and the calibrator (P1.5)
     * could mask it.
     */
    private fun startOrientationUpdates() {
        sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager
        rotationVectorSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        if (rotationVectorSensor == null) {
            imuActive = false
            return
        }
        sensorManager?.registerListener(
            sensorListener, rotationVectorSensor, SensorManager.SENSOR_DELAY_GAME
        )
    }

    private val sensorListener = object : SensorEventListener {
        private val q = FloatArray(4)
        override fun onSensorChanged(event: SensorEvent) {
            if (event.sensor.type != Sensor.TYPE_ROTATION_VECTOR) return
            // Android writes Q as [w, x, y, z] — the same order the V3 protocol uses.
            SensorManager.getQuaternionFromVector(q, event.values)
            orientation = floatArrayOf(q[0], q[1], q[2], q[3])
            imuActive = true
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) { /* no-op */ }
    }

    // =========================================================================
    // Permission + FGS-type helpers (BUG-001/002)
    // =========================================================================

    private fun hasPermission(permission: String): Boolean =
        ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

    /**
     * Build the foreground-service type mask from the permissions actually held
     * right now. On Android 14+ each typed FGS requires its runtime permission
     * at startForeground() time, so we only claim the types we can legally
     * start. Returns 0 (no type) when neither is granted, which still lets the
     * service run as a plain foreground service instead of crashing.
     */
    private fun computeForegroundServiceType(): Int {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return 0
        var type = 0
        if (hasPermission(Manifest.permission.CAMERA)) {
            type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
        }
        if (hasPermission(Manifest.permission.ACCESS_FINE_LOCATION) ||
            hasPermission(Manifest.permission.ACCESS_COARSE_LOCATION)
        ) {
            type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        }
        return type
    }

    /**
     * Recompute health flags from actual listener state, instead of the old
     * hardcoded GPS_OK | CAMERA_OK | IMU_OK. The GPS bit is only set while a fix
     * exists within the freshness window; the IMU bit only once the rotation
     * listener has produced a value.
     */
    private fun computeHealthFlags(): Byte {
        var flags = 0
        if (cameraActive) flags = flags or CAMERA_OK
        val fixAge = SystemClock.elapsedRealtime() - lastFixElapsedMs
        if (hasGpsFix && fixAge <= GPS_MAX_AGE_MS) flags = flags or GPS_OK
        if (imuActive) flags = flags or IMU_OK
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
