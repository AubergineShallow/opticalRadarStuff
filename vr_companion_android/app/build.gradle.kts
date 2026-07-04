plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.opticalradar.geotether"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.opticalradar.geotether"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.0"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.6.2")
    implementation("androidx.lifecycle:lifecycle-service:2.6.2")
    implementation("androidx.activity:activity-compose:1.8.0")
    implementation(platform("androidx.compose:compose-bom:2023.03.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.runtime:runtime")

    // Coroutines (StateFlow.collectAsState in Compose)
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // Location Services (same fused provider the android_node uses)
    implementation("com.google.android.gms:play-services-location:21.0.1")

    // Embedded WebSocket server for the headset feed
    implementation("org.java-websocket:Java-WebSocket:1.5.6")
}
