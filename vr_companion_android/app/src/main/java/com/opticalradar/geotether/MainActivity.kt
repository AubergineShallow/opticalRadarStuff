package com.opticalradar.geotether

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.net.NetworkInterface

/**
 * GeoTether — companion app for the OpticalRadar VR frontend.
 *
 * The Steam Frame headset has no GNSS. This app runs on an Android phone
 * tethered to the headset (USB or hotspot) and streams the phone's fused
 * GNSS fix + true-north compass heading to VR-UI over a local WebSocket
 * (port 8790). Hold the phone level, pointing the same way you face, when
 * you press "align" on the controller — that heading anchors WORLD mode.
 */
class MainActivity : ComponentActivity() {

    private var service: GeoTetherService? = null
    private val serviceState = mutableStateOf<GeoTetherService?>(null)

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            service = (binder as GeoTetherService.GeoTetherBinder).getService()
            serviceState.value = service
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            service = null
            serviceState.value = null
        }
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants[Manifest.permission.ACCESS_FINE_LOCATION] == true) {
            startTether()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    TetherScreen(
                        serviceState.value,
                        onStart = { requestPermissionsAndStart() },
                        onStop = { stopTether() },
                    )
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        bindService(Intent(this, GeoTetherService::class.java), connection, 0)
    }

    override fun onStop() {
        super.onStop()
        unbindService(connection)
    }

    private fun requestPermissionsAndStart() {
        val perms = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            perms.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permissionLauncher.launch(perms.toTypedArray())
    }

    private fun startTether() {
        val intent = Intent(this, GeoTetherService::class.java)
        startForegroundService(intent)
        bindService(intent, connection, Context.BIND_AUTO_CREATE)
    }

    private fun stopTether() {
        stopService(Intent(this, GeoTetherService::class.java))
        serviceState.value = null
    }
}

@Composable
fun TetherScreen(
    service: GeoTetherService?,
    onStart: () -> Unit,
    onStop: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("GeoTether", fontSize = 28.sp)
        Text("GNSS + heading feed for the OpticalRadar VR headset", fontSize = 14.sp)

        if (service != null) {
            val running by service.running.collectAsState()
            val fix by service.fixText.collectAsState()
            val heading by service.headingText.collectAsState()
            val clients by service.clientCount.collectAsState()
            val packets by service.packetsSent.collectAsState()

            Text(if (running) "● STREAMING on port ${GeoTetherService.DEFAULT_PORT}" else "○ stopped")
            Text("Fix: $fix")
            Text("Heading: $heading")
            Text("Headsets connected: $clients")
            Text("Poses sent: $packets")
        } else {
            Text("○ not running")
        }

        val addresses = remember { localIpAddresses() }
        Text("Phone addresses (use in VR-UI ?geo=ws://<ip>:${GeoTetherService.DEFAULT_PORT}):",
            fontSize = 14.sp)
        addresses.forEach { Text("  $it", fontSize = 14.sp) }

        Button(onClick = onStart, modifier = Modifier.fillMaxWidth()) {
            Text("Start streaming")
        }
        Button(onClick = onStop, modifier = Modifier.fillMaxWidth()) {
            Text("Stop")
        }
    }
}

/** IPv4 addresses of the phone's interfaces — the USB-tether one (rndis/ncm,
 *  usually 192.168.42.x) is what the headset should be pointed at. */
private fun localIpAddresses(): List<String> {
    return try {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { nic ->
                nic.inetAddresses.toList()
                    .filter { it.address.size == 4 }   // IPv4 only
                    .map { "${nic.displayName}: ${it.hostAddress}" }
            }
    } catch (e: Exception) {
        listOf("unavailable: ${e.message}")
    }
}
