# GeoTether — VR companion app (Android)

Streams the phone's **fused GNSS fix + true-north compass heading** to the
OpticalRadar VR frontend (`VR-UI/`) over a local WebSocket. The Steam Frame
headset has no GNSS; this app is what anchors VR-UI's WORLD (1:1) mode to
the real world.

```
Android phone (this app, ws server :8790)
   │  USB tether / hotspot
   ▼
Steam Frame — VR-UI (?geo=ws://<phone-ip>:8790)
```

## Wire format

`{"type":"HELLO","payload":{...}}` once on connect, then at 2 Hz (only while
a fix exists and a client is connected):

```json
{ "type": "GEO_POSE", "payload": {
    "lat": 37.7749, "lon": -122.4194,
    "alt": 12.3,                 // WGS84 ELLIPSOID height (Android native)
    "accuracy_m": 4.2,
    "heading_deg": 123.4,        // TRUE north (declination applied here)
    "heading_accuracy_deg": 15.0,
    "speed_ms": 0.1,
    "timestamp": 1751600000.0,   // unix seconds (GPS fix time)
    "provider": "fused" } }
```

Consumer: `VR-UI/net/geoSocket.ts` (`types.ts::GeoPose`). Change both sides
together. Null fields mean "unavailable" — the client treats them as NaN.

## Design notes

- Foreground service (`location` type) so streaming survives screen-off.
- `FusedLocationProviderClient` at 1 Hz high accuracy (same stack as
  `code/android_node`); `Location.getAltitude()` is ellipsoidal — do NOT
  convert to MSL (geometry-conventions).
- Heading: `TYPE_ROTATION_VECTOR` → rotation matrix → azimuth, plus
  `GeomagneticField.declination` from the current fix, so the headset never
  deals with magnetic north. Hold the phone level, pointing where you face,
  when pressing "align" on the controller.
- WebSocket server: `org.java-websocket`, client set bounded at 4, 30 s
  ping/pong keepalive.

## Build

Standard Android Studio / Gradle project (AGP 8.1.1, Kotlin 1.9.0, minSdk 26,
mirrors `code/android_node`). **Not buildable in this repo's environment**
(no Android SDK) — same status as `android_node`: code-review quality,
build on a dev machine.
