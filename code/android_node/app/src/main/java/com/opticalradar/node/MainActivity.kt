package com.opticalradar.node

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat

class MainActivity : ComponentActivity() {

    private var cameraProvider: ProcessCameraProvider? = null
    private var sensorHelper: SensorHelper? = null

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        if (permissions.all { it.value }) {
            // Permissions granted
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        checkPermissions()
        sensorHelper = SensorHelper(this)

        setContent {
            var serverIp by remember { mutableStateOf("192.168.1.100") }
            var nodeId by remember { mutableStateOf("5") }
            var isRunning by remember { mutableStateOf(false) }

            // Live Telemetry observed from the SensorHelper and Background Service
            val lat by NodeState.latitude.collectAsState()
            val lon by NodeState.longitude.collectAsState()
            val alt by NodeState.altitude.collectAsState()

            val deviceAz by NodeState.azimuth.collectAsState()
            val devicePitch by NodeState.pitch.collectAsState()
            val deviceRoll by NodeState.roll.collectAsState()

            val targetAz by NodeState.lastTargetAzimuth.collectAsState()
            val targetEl by NodeState.lastTargetElevation.collectAsState()

            val activeTracks by NodeState.activeTracks.collectAsState()
            val packetsSent by NodeState.packetsSent.collectAsState()

            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("Optical Radar Node Setup", style = MaterialTheme.typography.headlineMedium)

                        Spacer(modifier = Modifier.height(8.dp))

                        // Camera Preview Window
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(250.dp)
                        ) {
                            CameraPreviewView()
                        }

                        Spacer(modifier = Modifier.height(16.dp))

                        // Live Telemetry Dashboard
                        Card(modifier = Modifier.fillMaxWidth()) {
                            Column(modifier = Modifier.padding(8.dp)) {
                                Text("GNSS", style = MaterialTheme.typography.titleMedium)
                                Text(String.format("Lat: %.6f, Lon: %.6f", lat, lon))
                                Text(String.format("Alt: %.1f m", alt))

                                Spacer(modifier = Modifier.height(8.dp))

                                Text("IMU (Device Mount Angle)", style = MaterialTheme.typography.titleMedium)
                                Text(String.format("Heading: %.1f°, Tilt: %.1f°, Roll: %.1f°", deviceAz, devicePitch, deviceRoll))

                                Spacer(modifier = Modifier.height(8.dp))

                                Text("Radar Tracking", style = MaterialTheme.typography.titleMedium)
                                Text("Active Tracks: $activeTracks")
                                Text(String.format("Last Target Vector -> Az: %.1f°, El: %.1f°", targetAz, targetEl))
                                Text("UDP Packets Sent: $packetsSent")
                            }
                        }

                        Spacer(modifier = Modifier.height(16.dp))

                        Row {
                            OutlinedTextField(
                                value = serverIp,
                                onValueChange = { serverIp = it },
                                label = { Text("Server IP") },
                                modifier = Modifier.weight(1.5f).padding(end = 8.dp)
                            )
                            OutlinedTextField(
                                value = nodeId,
                                onValueChange = { nodeId = it },
                                label = { Text("Node ID") },
                                modifier = Modifier.weight(1f)
                            )
                        }

                        Spacer(modifier = Modifier.height(24.dp))

                        Button(
                            onClick = {
                                if (!isRunning) {
                                    val intent = Intent(this@MainActivity, RadarService::class.java).apply {
                                        putExtra("SERVER_IP", serverIp)
                                        putExtra("SERVER_PORT", 5005)
                                        putExtra("NODE_ID", nodeId.toIntOrNull() ?: 1)
                                    }
                                    ContextCompat.startForegroundService(this@MainActivity, intent)
                                    isRunning = true
                                    sensorHelper?.start() // Start feeding UI sensors
                                } else {
                                    stopService(Intent(this@MainActivity, RadarService::class.java))
                                    isRunning = false
                                    sensorHelper?.stop()
                                }
                            },
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(if (isRunning) "STOP RADAR" else "START RADAR")
                        }
                    }
                }
            }
        }
    }

    @Composable
    fun CameraPreviewView() {
        val context = LocalContext.current
        val lifecycleOwner = LocalLifecycleOwner.current

        AndroidView(
            factory = { ctx ->
                PreviewView(ctx).apply {
                    scaleType = PreviewView.ScaleType.FILL_CENTER
                    implementationMode = PreviewView.ImplementationMode.COMPATIBLE
                }
            },
            modifier = Modifier.fillMaxSize(),
            update = { previewView ->
                val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
                cameraProviderFuture.addListener({
                    cameraProvider = cameraProviderFuture.get()
                    bindCameraUseCases(previewView, lifecycleOwner)
                }, ContextCompat.getMainExecutor(context))
            }
        )
    }

    private fun bindCameraUseCases(previewView: PreviewView, lifecycleOwner: androidx.lifecycle.LifecycleOwner) {
        val provider = cameraProvider ?: return
        provider.unbindAll()

        val preview = Preview.Builder().build().also {
            it.setSurfaceProvider(previewView.surfaceProvider)
        }

        val cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA

        try {
            provider.bindToLifecycle(lifecycleOwner, cameraSelector, preview)
        } catch (exc: Exception) {
            exc.printStackTrace()
        }
    }

    private fun checkPermissions() {
        val requiredPermissions = arrayOf(
            Manifest.permission.CAMERA,
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION
        )
        val missingPermissions = requiredPermissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missingPermissions.isNotEmpty()) {
            requestPermissionLauncher.launch(missingPermissions.toTypedArray())
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        sensorHelper?.stop()
    }
}
