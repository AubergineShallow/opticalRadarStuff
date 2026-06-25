package com.opticalradar.node

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.IBinder
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.collectAsState

class MainActivity : ComponentActivity() {

    // Service binding state
    private var radarService: RadarService? = null
    private var serviceBound = false
    private var previewView: PreviewView? = null

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            val service = (binder as RadarService.RadarBinder).getService()
            radarService = service
            serviceBound = true

            // Attach the service's Preview use case to our PreviewView
            previewView?.let { pv ->
                service.preview?.setSurfaceProvider(pv.surfaceProvider)
            }
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            radarService = null
            serviceBound = false
        }
    }

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

        setContent {
            var serverIp by remember { mutableStateOf("192.168.1.100") }
            var cameraId by remember { mutableStateOf("android_01") }
            var isRunning by remember { mutableStateOf(false) }

            // Collect live stats from the service's StateFlow (Phase 3)
            val tracksFound by radarService?.tracksFound?.collectAsState()
                ?: remember { mutableStateOf(0) }
            val packetsSent by radarService?.packetsSent?.collectAsState()
                ?: remember { mutableStateOf(0) }

            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("Optical Radar Node Setup", style = MaterialTheme.typography.headlineMedium)

                        Spacer(modifier = Modifier.height(16.dp))

                        // Camera Preview Window — shows the service's Preview use case
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(300.dp)
                        ) {
                            ServiceCameraPreview()
                        }

                        Spacer(modifier = Modifier.height(16.dp))

                        Row(modifier = Modifier.fillMaxWidth()) {
                            Text("Tracks: $tracksFound", modifier = Modifier.weight(1f))
                            Text("UDP Sent: $packetsSent", modifier = Modifier.weight(1f))
                        }

                        Spacer(modifier = Modifier.height(16.dp))

                        OutlinedTextField(
                            value = serverIp,
                            onValueChange = { serverIp = it },
                            label = { Text("Server IP") },
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(modifier = Modifier.height(8.dp))

                        OutlinedTextField(
                            value = cameraId,
                            onValueChange = { cameraId = it },
                            label = { Text("Camera ID") },
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(modifier = Modifier.height(24.dp))

                        Button(
                            onClick = {
                                if (!isRunning) {
                                    val intent = Intent(this@MainActivity, RadarService::class.java).apply {
                                        putExtra("SERVER_IP", serverIp)
                                        putExtra("SERVER_PORT", 5005)
                                        putExtra("CAMERA_ID", cameraId)
                                    }
                                    ContextCompat.startForegroundService(this@MainActivity, intent)

                                    // Bind so we can show the preview & collect stats
                                    bindService(
                                        Intent(this@MainActivity, RadarService::class.java),
                                        serviceConnection,
                                        Context.BIND_AUTO_CREATE
                                    )
                                    isRunning = true
                                } else {
                                    if (serviceBound) {
                                        unbindService(serviceConnection)
                                        serviceBound = false
                                        radarService = null
                                    }
                                    stopService(Intent(this@MainActivity, RadarService::class.java))
                                    isRunning = false
                                }
                            },
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(if (isRunning) "STOP RADAR" else "START RADAR")
                        }

                        Spacer(modifier = Modifier.height(16.dp))
                        Text("Note: After starting, you may turn off the screen. The node runs as a Foreground Service.")
                    }
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        // Re-attach the preview surface when the Activity comes back to the foreground
        if (serviceBound) {
            previewView?.let { pv ->
                radarService?.preview?.setSurfaceProvider(pv.surfaceProvider)
            }
        }
    }

    override fun onStop() {
        super.onStop()
        // Detach the preview surface — detection (ImageAnalysis) is unaffected
        radarService?.preview?.setSurfaceProvider(null)
    }

    override fun onDestroy() {
        super.onDestroy()
        if (serviceBound) {
            unbindService(serviceConnection)
            serviceBound = false
        }
    }

    /**
     * Composable that creates a [PreviewView] and stashes a reference so the
     * [ServiceConnection] callback can attach the service's Preview use case.
     *
     * This does NOT create its own ProcessCameraProvider — the service owns the
     * camera.  Two components binding the same physical camera will fight each
     * other; this approach avoids that.
     */
    @Composable
    fun ServiceCameraPreview() {
        AndroidView(
            factory = { ctx ->
                PreviewView(ctx).apply {
                    scaleType = PreviewView.ScaleType.FILL_CENTER
                    implementationMode = PreviewView.ImplementationMode.COMPATIBLE
                    previewView = this

                    // If the service is already bound, attach immediately
                    radarService?.preview?.setSurfaceProvider(surfaceProvider)
                }
            },
            modifier = Modifier.fillMaxSize()
        )
    }

    private fun checkPermissions() {
        val requiredPermissions = arrayOf(
            Manifest.permission.CAMERA,
            Manifest.permission.ACCESS_FINE_LOCATION
        )
        val missingPermissions = requiredPermissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missingPermissions.isNotEmpty()) {
            requestPermissionLauncher.launch(missingPermissions.toTypedArray())
        }
    }
}
