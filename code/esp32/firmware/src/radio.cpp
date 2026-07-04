// radio.cpp - backend implementations for radio.h, selected by -D flags.
#include "radio.h"
#include "../include/config.h"
#include "../include/lora_protocol.h"
#include <Arduino.h>

// ===========================================================================
// Backend 1: Meshtastic companion node over UART (Serial Module) - PRIMARY
// ===========================================================================
#if defined(RADIO_BACKEND_MESHTASTIC_SERIAL)

static HardwareSerial s_mesh(MESH_UART_NUM);

class MeshtasticSerialRadio : public Radio {
public:
    bool begin() override {
        s_mesh.begin(MESH_BAUD, SERIAL_8N1, MESH_RX_PIN, MESH_TX_PIN);
        return true;
    }

    // The Meshtastic Serial Module (SIMPLE mode) packetises whatever it reads
    // between inter-byte gaps and transmits it as one mesh data packet on
    // SERIAL_APP. We write one payload, flush, and let the caller space sends
    // so each payload becomes its own mesh packet (the server rejects merged
    // payloads by length, so keep >1 module-timeout between sends).
    bool sendAnnounce(uint8_t node_id, float lat, float lon, float alt,
                      float roll, float pitch, float yaw) override {
        uint8_t buf[LORA_ANNOUNCE_SIZE];
        int n = lora_pack_announce(buf, node_id, lat, lon, alt, roll, pitch, yaw);
        s_mesh.write(buf, n);
        s_mesh.flush();
        return true;
    }

    bool sendUpdate(uint8_t node_id, uint8_t track_id,
                    float az, float el, float size) override {
        uint8_t buf[LORA_UPDATE_SIZE];
        int n = lora_pack_update(buf, node_id, track_id, az, el, size);
        s_mesh.write(buf, n);
        s_mesh.flush();
        return true;
    }

    const char* name() const override { return "meshtastic-serial"; }
};

Radio* getRadio() {
    static MeshtasticSerialRadio r;
    return &r;
}

// ===========================================================================
// Backend 2: direct SX127x LoRa (RadioLib)
// ===========================================================================
#elif defined(RADIO_BACKEND_LORA_SX127X)

#include <RadioLib.h>
#include <SPI.h>

static SPIClass s_spi(VSPI);
// SX1278 module: CS, DIO0, RST, DIO1(unused here -> RADIOLIB_NC)
static SX1278 s_lora = new Module(LORA_CS_PIN, LORA_DIO0_PIN, LORA_RST_PIN, RADIOLIB_NC, s_spi);

class LoraSX127xRadio : public Radio {
public:
    bool begin() override {
        s_spi.begin(LORA_SCK_PIN, LORA_MISO_PIN, LORA_MOSI_PIN, LORA_CS_PIN);
        int st = s_lora.begin(LORA_FREQ_MHZ, LORA_BW_KHZ, LORA_SF);
        if (st != RADIOLIB_ERR_NONE) return false;
        s_lora.setSyncWord(LORA_SYNC_WORD);
        s_lora.setOutputPower(LORA_TX_POWER_DBM);
        return true;
    }

    // Each LoRa transmit() is one discrete packet, so we send the RAW payload;
    // the laptop's raw-LoRa USB bridge frames it (LoRaFramer) for pyserial.
    bool sendAnnounce(uint8_t node_id, float lat, float lon, float alt,
                      float roll, float pitch, float yaw) override {
        uint8_t buf[LORA_ANNOUNCE_SIZE];
        int n = lora_pack_announce(buf, node_id, lat, lon, alt, roll, pitch, yaw);
        return s_lora.transmit(buf, n) == RADIOLIB_ERR_NONE;
    }

    bool sendUpdate(uint8_t node_id, uint8_t track_id,
                    float az, float el, float size) override {
        uint8_t buf[LORA_UPDATE_SIZE];
        int n = lora_pack_update(buf, node_id, track_id, az, el, size);
        return s_lora.transmit(buf, n) == RADIOLIB_ERR_NONE;
    }

    const char* name() const override { return "lora-sx127x"; }
};

Radio* getRadio() {
    static LoraSX127xRadio r;
    return &r;
}

// ===========================================================================
// Backend 3: WiFi/UDP fallback (sends the SAME compressed payloads over UDP to
// the server's lora.transport = "udp" gateway on udp_port, default 5006)
// ===========================================================================
#elif defined(RADIO_BACKEND_WIFI_UDP)

#include <WiFi.h>
#include <WiFiUdp.h>

static WiFiUDP s_udp;

class WifiUdpRadio : public Radio {
public:
    bool begin() override {
        WiFi.mode(WIFI_STA);
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        uint32_t t0 = millis();
        while (WiFi.status() != WL_CONNECTED && (millis() - t0) < 15000) {
            delay(250);
        }
        return WiFi.status() == WL_CONNECTED;
    }

    bool sendPayload(const uint8_t* buf, int n) {
        // Each datagram is one payload; the UDP gateway needs no framing.
        if (s_udp.beginPacket(SERVER_IP, SERVER_UDP_PORT) != 1) return false;
        s_udp.write(buf, n);
        return s_udp.endPacket() == 1;
    }

    bool sendAnnounce(uint8_t node_id, float lat, float lon, float alt,
                      float roll, float pitch, float yaw) override {
        uint8_t buf[LORA_ANNOUNCE_SIZE];
        int n = lora_pack_announce(buf, node_id, lat, lon, alt, roll, pitch, yaw);
        return sendPayload(buf, n);
    }

    bool sendUpdate(uint8_t node_id, uint8_t track_id,
                    float az, float el, float size) override {
        uint8_t buf[LORA_UPDATE_SIZE];
        int n = lora_pack_update(buf, node_id, track_id, az, el, size);
        return sendPayload(buf, n);
    }

    const char* name() const override { return "wifi-udp"; }
};

Radio* getRadio() {
    static WifiUdpRadio r;
    return &r;
}

#else
#error "No radio backend selected. Define one of RADIO_BACKEND_MESHTASTIC_SERIAL / RADIO_BACKEND_LORA_SX127X / RADIO_BACKEND_WIFI_UDP (see platformio.ini envs)."
#endif
