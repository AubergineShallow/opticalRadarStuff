package com.opticalradar.node

import kotlinx.coroutines.flow.MutableStateFlow

/**
 * Singleton to share live telemetry data between the RadarService (Background)
 * and the MainActivity (UI) for the user's dashboard.
 */
object NodeState {
    val latitude = MutableStateFlow(0.0)
    val longitude = MutableStateFlow(0.0)
    val altitude = MutableStateFlow(0.0)

    val azimuth = MutableStateFlow(0.0f)   // Phone's compass heading
    val pitch = MutableStateFlow(0.0f)     // Phone's vertical tilt
    val roll = MutableStateFlow(0.0f)      // Phone's horizontal tilt

    val packetsSent = MutableStateFlow(0)
    val activeTracks = MutableStateFlow(0)

    // Most recent target detected by ML Kit
    val lastTargetAzimuth = MutableStateFlow(0.0f)
    val lastTargetElevation = MutableStateFlow(0.0f)
}
