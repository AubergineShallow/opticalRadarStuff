
// config.h - Compile-time configuration for the ESP32-CAM optical node.
//
// PIN BUDGET (AI-Thinker ESP32-CAM): the OV2640 + PSRAM claim most GPIOs. With
// the SD card left unused, the free pins are GPIO 12,13,14,15,2,4 (4 = flash
// LED) plus UART0 (1/3, used for USB debug). To fit GNSS + IMU + a radio link
// we put GNSS and IMU on ONE shared I2C bus (both NEO-M8N/M9N and MPU-6050 /
// BNO08x support I2C) and give the Meshtastic UART its own pins. A UART-only
// NEO-6M is supported too (see USE_GNSS_I2C below).
#pragma once

// ---- Node identity ---------------------------------------------------------
// uint8 id shared with the server. The server maps it to "lora<NN>"
// (NODE_ID 20 -> "lora20"); add a matching entry in code/config/node_specs.json.
#define NODE_ID              20

// ---- Optics (must match this node's node_specs.json entry) -----------------
// The sensor cannot read its lens FOV back electronically, so it is declared
// here AND in node_specs.json. Keep the two in sync.
#define FOV_HORIZONTAL_DEG   66.0f
#define FOV_VERTICAL_DEG     50.0f

// ---- Camera / detection ----------------------------------------------------
// Grayscale frames make frame-differencing cheap (1 byte/pixel). Small frames
// keep the whole pipeline within the ESP32's RAM and a few Hz.
#define FRAME_WIDTH          160     // QQVGA; detector downsamples further if needed
#define FRAME_HEIGHT         120
#define DETECT_THRESHOLD     25      // per-pixel abs-diff threshold (0-255)
#define DETECT_MIN_PIXELS    40      // min changed pixels to count as motion
#define DETECT_FPS           5       // detection loop rate (Hz)

// ---- Edge tracker (maturation before we spend airtime) ---------------------
#define TRACK_REQUIRED_HITS  8       // frames before a track is "mature"
#define TRACK_MAX_MISSED_MS  3000    // drop a track unseen this long
#define TRACK_ASSOC_DEG      6.0f    // nearest-neighbour association radius

// ---- Airtime governance ----------------------------------------------------
#define ANNOUNCE_INTERVAL_MS 5000    // pose announce cadence
#define UPDATE_MIN_GAP_MS    5000    // min gap between track-update bursts

// ---- I2C shared bus (GNSS + IMU) ------------------------------------------
#define I2C_SDA_PIN          13
#define I2C_SCL_PIN          12
#define IMU_I2C_ADDR         0x68    // MPU-6050 default
#define GNSS_I2C_ADDR        0x42    // u-blox DDC default
#define USE_GNSS_I2C         1       // 1 = GNSS on I2C; 0 = GNSS on UART pins below

// ---- GNSS over UART (only if USE_GNSS_I2C == 0; e.g. a NEO-6M) --------------
#define GNSS_UART_NUM        1
#define GNSS_RX_PIN          15      // <- GNSS TX
#define GNSS_TX_PIN          14      // -> GNSS RX (config; often unused)
#define GNSS_BAUD            9600

// ---- Radio: Meshtastic companion node over UART (Serial Module) ------------
// Wire these to the companion Meshtastic device's Serial Module RX/TX. Configure
// that node's Serial Module in SIMPLE/PROTO mode, matching baud. (Only used when
// RADIO_BACKEND_MESHTASTIC_SERIAL is defined.)
#define MESH_UART_NUM        2
#define MESH_TX_PIN          14      // -> Meshtastic Serial RX
#define MESH_RX_PIN          15      // <- Meshtastic Serial TX
#define MESH_BAUD            115200

// ---- Radio: direct SX127x LoRa (only if RADIO_BACKEND_LORA_SX127X) ---------
// SPI + control pins. These reuse the SD-card pins, so the SD card must stay
// unused. Frequency must match your region AND the laptop's raw-LoRa bridge.
#define LORA_FREQ_MHZ        915.0f  // 915 (US) / 868 (EU) / 433 - set for region
#define LORA_BW_KHZ          125.0f
#define LORA_SF              9       // spreading factor
#define LORA_SYNC_WORD       0x12    // private network (NOT 0x34 = LoRaWAN)
#define LORA_TX_POWER_DBM    17
#define LORA_SCK_PIN         14
#define LORA_MISO_PIN        12
#define LORA_MOSI_PIN        13
#define LORA_CS_PIN          15
#define LORA_DIO0_PIN        2
#define LORA_RST_PIN         4

// ---- Radio: WiFi/UDP fallback (only if RADIO_BACKEND_WIFI_UDP) -------------
// This backend sends the compressed LoRa payloads to the server's LoRa UDP
// gateway (config lora.transport = "udp", lora.udp_port), NOT the V3 telemetry
// port 5005. Keep SERVER_UDP_PORT == lora.udp_port (default 5006).
#define WIFI_SSID            "your-ssid"
#define WIFI_PASSWORD        "your-pass"
#define SERVER_IP            "192.168.1.100"
#define SERVER_UDP_PORT      5006
