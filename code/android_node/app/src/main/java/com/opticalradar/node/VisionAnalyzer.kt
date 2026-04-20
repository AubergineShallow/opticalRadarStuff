package com.opticalradar.node

import android.annotation.SuppressLint
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.objects.ObjectDetection
import com.google.mlkit.vision.objects.defaults.ObjectDetectorOptions

class VisionAnalyzer(
    private val horizontalFovDegrees: Float = 60.0f,
    private val verticalFovDegrees: Float = 45.0f,
    private val onTracksUpdated: (List<TrackedObject>) -> Unit
) : ImageAnalysis.Analyzer {

    private val options = ObjectDetectorOptions.Builder()
        .setDetectorMode(ObjectDetectorOptions.STREAM_MODE)
        .enableMultipleObjects()
        .enableClassification()
        .build()

    private val objectDetector = ObjectDetection.getClient(options)

    @SuppressLint("UnsafeOptInUsageError")
    override fun analyze(imageProxy: ImageProxy) {
        val mediaImage = imageProxy.image
        if (mediaImage != null) {
            val image = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)

            objectDetector.process(image)
                .addOnSuccessListener { detectedObjects ->
                    val tracks = mutableListOf<TrackedObject>()

                    val imgWidth = imageProxy.width.toFloat()
                    val imgHeight = imageProxy.height.toFloat()

                    for (obj in detectedObjects) {
                        val trackId = obj.trackingId ?: continue

                        val centerX = obj.boundingBox.exactCenterX()
                        val centerY = obj.boundingBox.exactCenterY()

                        val nx = (centerX / imgWidth) - 0.5f
                        val ny = (centerY / imgHeight) - 0.5f

                        val azimuth = nx * horizontalFovDegrees
                        val elevation = -ny * verticalFovDegrees

                        tracks.add(TrackedObject(trackId, azimuth, elevation))

                        // Push to dashboard state
                        NodeState.lastTargetAzimuth.value = azimuth
                        NodeState.lastTargetElevation.value = elevation
                    }

                    NodeState.activeTracks.value = tracks.size
                    onTracksUpdated(tracks)
                }
                .addOnFailureListener { e -> e.printStackTrace() }
                .addOnCompleteListener { imageProxy.close() }
        } else {
            imageProxy.close()
        }
    }
}

data class TrackedObject(
    val trackId: Int,
    val azimuth: Float,
    val elevation: Float
)
