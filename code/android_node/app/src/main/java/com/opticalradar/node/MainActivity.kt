package com.opticalradar.node

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat

class MainActivity : ComponentActivity() {

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
            var nodeId by remember { mutableStateOf("5") }
            var isRunning by remember { mutableStateOf(false) }

            MaterialTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("Optical Radar Node Setup", style = MaterialTheme.typography.headlineMedium)

                        Spacer(modifier = Modifier.height(16.dp))

                        OutlinedTextField(
                            value = serverIp,
                            onValueChange = { serverIp = it },
                            label = { Text("Server IP") }
                        )

                        Spacer(modifier = Modifier.height(8.dp))

                        OutlinedTextField(
                            value = nodeId,
                            onValueChange = { nodeId = it },
                            label = { Text("Node ID") }
                        )

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
                                } else {
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
