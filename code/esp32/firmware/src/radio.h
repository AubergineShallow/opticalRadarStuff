
// radio.h - Transport abstraction for the ESP32-CAM node.
//
// One interface, three compile-time backends (select in platformio.ini):
//   * RADIO_BACKEND_MESHTASTIC_SERIAL - hand payloads to a companion Meshtastic
//     node over UART (Serial Module). PRIMARY.
//   * RADIO_BACKEND_LORA_SX127X       - drive an SX127x directly (RadioLib).
//   * RADIO_BACKEND_WIFI_UDP          - send payloads over WiFi/UDP.
//
// Every backend emits the SAME compressed payloads (lora_protocol.h), so the
// server's LoRaGateway ingests them identically regardless of how they travel.
#pragma once

#include <stdint.h>

class Radio {
public:
    virtual ~Radio() {}
    virtual bool begin() = 0;
    virtual bool sendAnnounce(uint8_t node_id, float lat, float lon, float alt,
                              float roll, float pitch, float yaw) = 0;
    virtual bool sendUpdate(uint8_t node_id, uint8_t track_id,
                            float az, float el, float size) = 0;
    virtual const char* name() const = 0;
};

// Returns the singleton backend chosen at compile time.
Radio* getRadio();
