package com.opticalradar.node

import android.annotation.SuppressLint
import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.os.Looper
import com.google.android.gms.location.*

/**
 * Handles Android's FusedLocationProviderClient (GNSS) and SensorManager (IMU).
 * Pushes updates to the NodeState singleton.
 */
class SensorHelper(private val context: Context) : SensorEventListener {

    private val fusedLocationClient: FusedLocationProviderClient = LocationServices.getFusedLocationProviderClient(context)
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private var rotationSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(locationResult: LocationResult) {
            for (location in locationResult.locations) {
                NodeState.latitude.value = location.latitude
                NodeState.longitude.value = location.longitude
                NodeState.altitude.value = location.altitude
            }
        }
    }

    @SuppressLint("MissingPermission")
    fun start() {
        // Start GPS
        val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 2000) // 2 sec intervals
            .setWaitForAccurateLocation(false)
            .build()
        fusedLocationClient.requestLocationUpdates(locationRequest, locationCallback, Looper.getMainLooper())

        // Start IMU
        rotationSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_UI)
        }
    }

    fun stop() {
        fusedLocationClient.removeLocationUpdates(locationCallback)
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent?) {
        if (event?.sensor?.type == Sensor.TYPE_ROTATION_VECTOR) {
            val rotationMatrix = FloatArray(9)
            SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)

            val orientationAngles = FloatArray(3)
            SensorManager.getOrientation(rotationMatrix, orientationAngles)

            // Convert radians to degrees
            // orientationAngles[0] is Azimuth (Z axis)
            // orientationAngles[1] is Pitch (X axis)
            // orientationAngles[2] is Roll (Y axis)
            NodeState.azimuth.value = Math.toDegrees(orientationAngles[0].toDouble()).toFloat()
            NodeState.pitch.value = Math.toDegrees(orientationAngles[1].toDouble()).toFloat()
            NodeState.roll.value = Math.toDegrees(orientationAngles[2].toDouble()).toFloat()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}
