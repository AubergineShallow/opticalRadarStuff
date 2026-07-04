package com.opticalradar.geotether

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.hardware.GeomagneticField
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Foreground service that streams the phone's geodetic pose to the VR
 * headset over the tether: fused GNSS fix + TRUE-north compass heading,
 * broadcast as GEO_POSE JSON by an embedded WebSocket server (:8790).
 *
 * The Steam Frame has no GNSS of its own; VR-UI's WORLD mode anchors the ENU
 * scene with exactly this feed. Wire format (see VR-UI/types.ts GeoPose):
 *   { "type": "GEO_POSE", "payload": { lat, lon, alt, accuracy_m,
 *     heading_deg, heading_accuracy_deg, speed_ms, timestamp, provider } }
 *
 * Conventions that MUST hold (geometry-conventions skill):
 *  - alt is height above the WGS84 ELLIPSOID — Location.getAltitude()
 *    already is; do not "correct" it to MSL.
 *  - heading_deg is TRUE north, clockwise. The rotation vector gives a
 *    MAGNETIC heading; declination from GeomagneticField is added here so
 *    the headset never needs to know about declination.
 */
class GeoTetherService : Service(), SensorEventListener {

    companion object {
        private const val TAG = "GeoTetherService"
        const val DEFAULT_PORT = 8790
        private const val BROADCAST_INTERVAL_MS = 500L   // 2 Hz
        private const val LOCATION_INTERVAL_MS = 1000L
        private const val CHANNEL_ID = "geotether"
        private const val NOTIFICATION_ID = 2
    }

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var broadcastJob: Job? = null

    // --- GNSS -----------------------------------------------------------
    private var fusedLocationClient: FusedLocationProviderClient? = null
    private var locationCallback: LocationCallback? = null
    @Volatile private var lat: Double = Double.NaN
    @Volatile private var lon: Double = Double.NaN
    @Volatile private var alt: Double = 0.0
    @Volatile private var accuracyM: Float = Float.NaN
    @Volatile private var speedMs: Float = 0f
    @Volatile private var fixTimeS: Double = 0.0
    @Volatile private var hasFix: Boolean = false
    // True-north correction for the current location; updated on each fix.
    @Volatile private var declinationDeg: Float = 0f

    // --- Compass --------------------------------------------------------
    private var sensorManager: SensorManager? = null
    private var rotationVectorSensor: Sensor? = null
    @Volatile private var headingTrueDeg: Float = Float.NaN
    @Volatile private var headingAccuracyDeg: Float = Float.NaN
    private val rotationMatrix = FloatArray(9)
    private val orientationAngles = FloatArray(3)

    // --- WebSocket server -----------------------------------------------
    private var poseServer: PoseSocketServer? = null

    // --- Observable state for the Compose UI -----------------------------
    private val _running = MutableStateFlow(false)
    val running: StateFlow<Boolean> = _running
    private val _fixText = MutableStateFlow("no fix")
    val fixText: StateFlow<String> = _fixText
    private val _headingText = MutableStateFlow("—")
    val headingText: StateFlow<String> = _headingText
    private val _clientCount = MutableStateFlow(0)
    val clientCount: StateFlow<Int> = _clientCount
    private val _packetsSent = MutableStateFlow(0)
    val packetsSent: StateFlow<Int> = _packetsSent

    inner class GeoTetherBinder : Binder() {
        fun getService(): GeoTetherService = this@GeoTetherService
    }

    private val binder = GeoTetherBinder()
    override fun onBind(intent: Intent?): IBinder = binder

    // ------------------------------------------------------------------ //
    // Lifecycle                                                           //
    // ------------------------------------------------------------------ //
    override fun onCreate() {
        super.onCreate()
        val channel = NotificationChannel(
            CHANNEL_ID, "GeoTether", NotificationManager.IMPORTANCE_LOW)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("GeoTether")
            .setContentText("Streaming GNSS + heading to the headset")
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .build()
        ServiceCompat.startForeground(
            this, NOTIFICATION_ID, notification,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
                ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0)

        startLocation()
        startCompass()
        startServer()
        startBroadcastLoop()
        _running.value = true
        return START_STICKY
    }

    override fun onDestroy() {
        broadcastJob?.cancel()
        locationCallback?.let { fusedLocationClient?.removeLocationUpdates(it) }
        sensorManager?.unregisterListener(this)
        try {
            poseServer?.stop(1000)
        } catch (e: Exception) {
            Log.w(TAG, "Server stop: ${e.message}")
        }
        poseServer = null
        scope.cancel()
        _running.value = false
        super.onDestroy()
    }

    // ------------------------------------------------------------------ //
    // GNSS                                                                //
    // ------------------------------------------------------------------ //
    private fun startLocation() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED) {
            Log.e(TAG, "ACCESS_FINE_LOCATION not granted; no fixes will be sent")
            _fixText.value = "location permission missing"
            return
        }
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)
        val request = LocationRequest.Builder(
            Priority.PRIORITY_HIGH_ACCURACY, LOCATION_INTERVAL_MS).build()
        locationCallback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                val loc = result.lastLocation ?: return
                lat = loc.latitude
                lon = loc.longitude
                // Android's getAltitude() is height above the WGS84 ellipsoid —
                // exactly what the server-side ENU math expects.
                alt = if (loc.hasAltitude()) loc.altitude else 0.0
                accuracyM = if (loc.hasAccuracy()) loc.accuracy else Float.NaN
                speedMs = if (loc.hasSpeed()) loc.speed else 0f
                fixTimeS = loc.time / 1000.0
                hasFix = true
                declinationDeg = GeomagneticField(
                    loc.latitude.toFloat(), loc.longitude.toFloat(),
                    alt.toFloat(), loc.time).declination
                _fixText.value = String.format(
                    "%.6f, %.6f  ±%.0fm  alt %.0fm",
                    lat, lon, accuracyM, alt)
            }
        }
        fusedLocationClient?.requestLocationUpdates(
            request, locationCallback!!, Looper.getMainLooper())
    }

    // ------------------------------------------------------------------ //
    // Compass (rotation vector → true-north heading)                      //
    // ------------------------------------------------------------------ //
    private fun startCompass() {
        sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager
        rotationVectorSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        if (rotationVectorSensor == null) {
            Log.w(TAG, "No rotation vector sensor; heading will be NaN")
            _headingText.value = "no compass"
            return
        }
        sensorManager?.registerListener(
            this, rotationVectorSensor, SensorManager.SENSOR_DELAY_UI)
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_ROTATION_VECTOR) return
        SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
        SensorManager.getOrientation(rotationMatrix, orientationAngles)
        // Azimuth of the device Y axis (top edge, phone held flat), magnetic.
        val magneticDeg = Math.toDegrees(orientationAngles[0].toDouble()).toFloat()
        headingTrueDeg = ((magneticDeg + declinationDeg) % 360f + 360f) % 360f
        // values[4] = estimated heading accuracy in radians; -1 / absent when
        // the sensor can't estimate it.
        headingAccuracyDeg = if (event.values.size >= 5 && event.values[4] >= 0f)
            Math.toDegrees(event.values[4].toDouble()).toFloat() else Float.NaN
        _headingText.value = String.format("%.0f° true", headingTrueDeg)
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    // ------------------------------------------------------------------ //
    // WebSocket server + broadcast loop                                   //
    // ------------------------------------------------------------------ //
    private fun startServer() {
        if (poseServer != null) return
        val hello = JSONObject()
            .put("type", "HELLO")
            .put("payload", JSONObject()
                .put("device", Build.MODEL)
                .put("app", "GeoTether")
                .put("version", 1))
            .toString()
        try {
            poseServer = PoseSocketServer(DEFAULT_PORT, hello) { count ->
                _clientCount.value = count
            }.also {
                it.isReuseAddr = true
                it.start()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start pose server: ${e.message}")
        }
    }

    private fun startBroadcastLoop() {
        if (broadcastJob != null) return
        broadcastJob = scope.launch {
            while (true) {
                delay(BROADCAST_INTERVAL_MS)
                val server = poseServer ?: continue
                if (!hasFix || server.clientCount() == 0) continue
                val payload = JSONObject()
                    .put("lat", lat)
                    .put("lon", lon)
                    .put("alt", alt)
                    .put("accuracy_m", if (accuracyM.isNaN()) JSONObject.NULL else accuracyM)
                    .put("heading_deg", if (headingTrueDeg.isNaN()) JSONObject.NULL else headingTrueDeg)
                    .put("heading_accuracy_deg",
                        if (headingAccuracyDeg.isNaN()) JSONObject.NULL else headingAccuracyDeg)
                    .put("speed_ms", speedMs)
                    .put("timestamp", fixTimeS)
                    .put("provider", "fused")
                val msg = JSONObject().put("type", "GEO_POSE").put("payload", payload)
                server.broadcastPose(msg.toString())
                _packetsSent.value = _packetsSent.value + 1
            }
        }
    }
}
