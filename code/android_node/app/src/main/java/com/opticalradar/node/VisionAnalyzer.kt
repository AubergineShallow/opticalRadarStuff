

package com.opticalradar.node

import android.annotation.SuppressLint
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.objects.ObjectDetection
import com.google.mlkit.vision.objects.defaults.ObjectDetectorOptions
import kotlin.math.atan2

class VisionAnalyzer(
    private val horizontalFovDegrees: Float = 60.0f,
    private val verticalFovDegrees: Float = 45.0f,
    private val onTracksUpdated: (List<TrackedObject>) -> Unit
) : ImageAnalysis.Analyzer {

    // Configure ML Kit to track multiple objects across frames automatically
    private val options = ObjectDetectorOptions.Builder()
        .setDetectorMode(ObjectDetectorOptions.STREAM_MODE)
        .enableMultipleObjects()
        .enableClassification() // Helps weed out noise
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
                        // We only care about objects ML Kit is confident enough to assign a tracking ID
                        val trackId = obj.trackingId ?: continue

                        // Get the center of the bounding box
                        val centerX = obj.boundingBox.exactCenterX()
                        val centerY = obj.boundingBox.exactCenterY()

                        // Convert pixels to vectors (Azimuth / Elevation)
                        // This mirrors the math in python's `vision.py`
                        val nx = (centerX / imgWidth) - 0.5f
                        val ny = (centerY / imgHeight) - 0.5f

                        // Simple rectilinear projection mapping
                        val azimuth = nx * horizontalFovDegrees
                        val elevation = -ny * verticalFovDegrees // Invert Y so up is positive

                        // Calculate angular size based on bounding box
                        val boxWidth = obj.boundingBox.width().toFloat()
                        val boxHeight = obj.boundingBox.height().toFloat()
                        val maxDim = maxOf(boxWidth, boxHeight)
                        val angularSize = (maxDim / imgWidth) * horizontalFovDegrees

                        // Derive intensity from best label confidence (scaled 0-255).
                        // ray_builder.py divides this by 255 to use as voxel-grid heat,
                        // so a high value means "confident detection, strong signal".
                        val bestConfidence = obj.labels.maxOfOrNull { it.confidence } ?: 1.0f
                        val intensity = (bestConfidence * 255).toInt().coerceIn(0, 255)

                        // Map ML Kit's label index to class_id (0 if no labels)
                        val classId = obj.labels.maxByOrNull { it.confidence }?.index ?: 0

                        tracks.add(TrackedObject(trackId, azimuth, elevation, angularSize, intensity, classId))
                    }
                    onTracksUpdated(tracks)
                }
                .addOnFailureListener { e ->
                    e.printStackTrace()
                }
                .addOnCompleteListener {
                    imageProxy.close()
                }
        } else {
            imageProxy.close()
        }
    }
}

data class TrackedObject(
    val trackId: Int,
    val azimuth: Float,
    val elevation: Float,
    val angularSize: Float,
    val intensity: Int = 200,   // [0, 255] — ML Kit confidence scaled to voxel heat
    val classId: Int = 0        // [0, 255] — ML Kit label index
)
