// Wireless stability test for the custom ESP32-C3 board (docs/ESP32C3_custom_schematic.pdf).
//
// Answers one question: do WiFi and BLE stay up, and keep delivering data,
// on this board over a long run - alone and at the same time? The C3 has a
// single 2.4 GHz radio that WiFi and BLE time-share, so "both at once" is
// the case that matters for the ring and the one most likely to fail.
//
// What it exercises:
//   WiFi : station on the phone hotspot; UDP echo on 5005 (loss + latency),
//          TCP stream on 5006 (throughput). The laptop script connects OUT to
//          these, because WSL2 cannot accept inbound connections from the LAN.
//   BLE  : the ECG app's exact service/packet format, carrying a synthetic
//          75 bpm heartbeat at 256 SPS, so the phone app shows a waveform,
//          a heart rate and its packet-loss counter with no app changes.
//   Board: reset reason and persistent reset counters at every boot. An
//          under-powered VIN shows up here as BROWNOUT resets under WiFi TX.
//
// Serial (UART0 via J1 TX/RX, 115200): '#'-prefixed key=value lines, parsed
// by wireless_test.py. Commands: 'w' toggle WiFi, 'b' toggle BLE, 's' status,
// 'n' rescan (reports the hotspot's RSSI and security mode), 'p' step TX power down.

#include <WiFi.h>
#include <WiFiUdp.h>
#include <NimBLEDevice.h>
#include <Preferences.h>
#include <esp_system.h>
#include <esp_timer.h>
#include "wifi_secrets.h"   // WIFI_SSID, WIFI_PASS - gitignored, see wifi_secrets.example.h

#define SERIAL_BAUD     115200
#define UDP_ECHO_PORT   5005
#define TCP_STREAM_PORT 5006
#define STATUS_MS       5000
#define BLE_SPS         256
#define BLE_BATCH       6      // must match the ECG firmware: [seq][count=6][6 x 3 bytes]

// Same UUIDs as sketch.ino / BleEcgClient.kt, so the unmodified app connects.
// Advertised under a different NAME, so it is obvious which board you are on.
static const char* ECG_SERVICE_UUID = "e54b0001-67f5-479e-8711-b3b99198ce6c";
static const char* ECG_CHAR_UUID    = "e54b0002-67f5-479e-8711-b3b99198ce6c";
static const char* BLE_NAME         = "C3-WTEST";

// ---------------------------------------------------------------- state
static volatile bool wifiActive = true, bleActive = true;
static volatile bool wifiUp = false;
static volatile uint32_t netGen = 0;          // bumps on every GOT_IP; servers restart on change
static volatile uint32_t wifiDisc = 0, wifiLastReason = 0;
static volatile uint32_t wifiDownSinceMs = 0, wifiLongestOutageMs = 0;
static volatile uint32_t udpEchoed = 0;
static volatile uint64_t tcpBytes = 0;
static volatile uint32_t tcpSessions = 0;
static volatile bool bleConnected = false, bleSubscribed = false;
static volatile uint32_t bleConns = 0, bleDisc = 0, blePkts = 0, bleNotifyFail = 0;
static uint32_t boots = 0, brownouts = 0, abnormal = 0;
static int rssiMin = 0, rssiMax = -127;

static WiFiUDP udp;
static WiFiServer tcpServer(TCP_STREAM_PORT);
static NimBLEServer* bleServer = nullptr;
static NimBLECharacteristic* bleChr = nullptr;
static uint8_t bleSeq = 0;

// ---------------------------------------------------------------- boot report
static const char* resetName(esp_reset_reason_t r)
{
    switch (r) {
    case ESP_RST_POWERON:    return "POWERON";
    case ESP_RST_EXT:        return "EXT";
    case ESP_RST_SW:         return "SW";
    case ESP_RST_PANIC:      return "PANIC";
    case ESP_RST_INT_WDT:    return "INT_WDT";
    case ESP_RST_TASK_WDT:   return "TASK_WDT";
    case ESP_RST_WDT:        return "WDT";
    case ESP_RST_DEEPSLEEP:  return "DEEPSLEEP";
    case ESP_RST_BROWNOUT:   return "BROWNOUT";
    case ESP_RST_SDIO:       return "SDIO";
    case ESP_RST_USB:        return "USB";
    case ESP_RST_JTAG:       return "JTAG";
    case ESP_RST_EFUSE:      return "EFUSE";
    case ESP_RST_PWR_GLITCH: return "PWR_GLITCH";
    case ESP_RST_CPU_LOCKUP: return "CPU_LOCKUP";
    default:                 return "UNKNOWN";
    }
}

static void bootReport()
{
    esp_reset_reason_t r = esp_reset_reason();
    bool isBrownout = (r == ESP_RST_BROWNOUT || r == ESP_RST_PWR_GLITCH);
    bool isAbnormal = isBrownout || r == ESP_RST_PANIC || r == ESP_RST_INT_WDT ||
                      r == ESP_RST_TASK_WDT || r == ESP_RST_WDT || r == ESP_RST_CPU_LOCKUP;

    // Counters survive resets (NVS), so a soak test can see reboots it missed.
    Preferences p;
    p.begin("wtest", false);
    boots     = p.getUInt("boots", 0) + 1;
    brownouts = p.getUInt("bo", 0) + (isBrownout ? 1 : 0);
    abnormal  = p.getUInt("abn", 0) + (isAbnormal ? 1 : 0);
    p.putUInt("boots", boots); p.putUInt("bo", brownouts); p.putUInt("abn", abnormal);
    p.end();

    Serial.printf("# boot n=%lu reason=%s brownouts=%lu abnormal=%lu chip=%s rev=%u cpu_mhz=%lu flash_mb=%lu\n",
                  boots, resetName(r), brownouts, abnormal, ESP.getChipModel(),
                  ESP.getChipRevision(), ESP.getCpuFreqMHz(), ESP.getFlashChipSize() / (1024 * 1024));
}

// ---------------------------------------------------------------- WiFi
static void onWifiEvent(WiFiEvent_t event, WiFiEventInfo_t info)
{
    switch (event) {
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
        wifiUp = true;
        if (wifiDownSinceMs) {
            uint32_t out = millis() - wifiDownSinceMs;
            if (out > wifiLongestOutageMs) wifiLongestOutageMs = out;
            wifiDownSinceMs = 0;
        }
        netGen++;
        Serial.printf("# wifi up ip=%s rssi=%d ch=%d tx_dbm=%.1f mac=%s\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI(), WiFi.channel(),
                      WiFi.getTxPower() / 4.0f, WiFi.macAddress().c_str());
        break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED: {
        bool wasUp = wifiUp;
        wifiUp = false;
        uint32_t reason = info.wifi_sta_disconnected.reason;
        wifiLastReason = reason;
        // A deliberate 'w' toggle is not a failure; everything else is.
        if (wifiActive && wasUp) {
            wifiDisc++;
            if (!wifiDownSinceMs) wifiDownSinceMs = millis();
        }
        if (wasUp || wifiActive)
            Serial.printf("# wifi down reason=%lu (%s) counted=%d\n", reason,
                          WiFi.disconnectReasonName((wifi_err_reason_t)reason), wifiActive && wasUp);
        break;
    }
    default:
        break;
    }
}

static const char* authName(wifi_auth_mode_t a)
{
    switch (a) {
    case WIFI_AUTH_OPEN:          return "OPEN";
    case WIFI_AUTH_WEP:           return "WEP";
    case WIFI_AUTH_WPA_PSK:       return "WPA";
    case WIFI_AUTH_WPA2_PSK:      return "WPA2";
    case WIFI_AUTH_WPA_WPA2_PSK:  return "WPA/WPA2";
    case WIFI_AUTH_WPA2_ENTERPRISE: return "WPA2-ENT";
    case WIFI_AUTH_WPA3_PSK:      return "WPA3";
    case WIFI_AUTH_WPA2_WPA3_PSK: return "WPA2/WPA3";
    default:                      return "OTHER";
    }
}

// How well does the board HEAR the hotspot, and what security does it use?
// A strong RSSI here plus AUTH_EXPIRE on connect means a one-way link: the
// board hears the phone but the phone does not hear the board (typically no
// antenna on J4). Only the target SSID is printed, other networks are counted.
static void scanReport()
{
    int n = WiFi.scanNetworks(false, true);
    int found = 0, strongestOther = -127;
    for (int i = 0; i < n; i++) {
        if (WiFi.SSID(i) == WIFI_SSID) {
            found++;
            Serial.printf("# scan target rssi=%d ch=%ld auth=%s\n", WiFi.RSSI(i), (long)WiFi.channel(i),
                          authName(WiFi.encryptionType(i)));
        } else if (WiFi.RSSI(i) > strongestOther) {
            strongestOther = WiFi.RSSI(i);
        }
    }
    Serial.printf("# scan networks=%d target_found=%d strongest_other_rssi=%d tx_dbm=%.1f\n",
                  n < 0 ? 0 : n, found, strongestOther, WiFi.getTxPower() / 4.0f);
    WiFi.scanDelete();
}

// TX power steps for the 'p' command. Lower power = lower supply current
// during transmit bursts, so if WiFi connects at low power but not at full
// power, the supply is sagging under TX load.
static const wifi_power_t kTxSteps[] = {WIFI_POWER_19_5dBm, WIFI_POWER_15dBm, WIFI_POWER_11dBm,
                                        WIFI_POWER_8_5dBm, WIFI_POWER_5dBm, WIFI_POWER_2dBm};
static int txStep = 0;

static void wifiStart()
{
    WiFi.mode(WIFI_STA);
    scanReport();
    WiFi.setAutoReconnect(true);
    // Leave modem sleep at its default (on). With BLE enabled too, ESP-IDF
    // requires it for radio coexistence and aborts if it is turned off. It
    // adds latency (the station wakes on beacon intervals), so expect UDP
    // round trips in the tens-to-hundreds of ms - that is the cost of
    // coexistence, not a fault.
    WiFi.begin(WIFI_SSID, WIFI_PASS);
}

// TCP throughput: the laptop connects and reads for N seconds; we write as
// fast as the stack accepts. Owns the server object, so restarts after a
// reconnect happen in one task and cannot race another.
static void tcpTask(void*)
{
    static uint8_t buf[1436];
    for (size_t i = 0; i < sizeof(buf); i++) buf[i] = (uint8_t)i;
    uint32_t myGen = 0;

    for (;;) {
        if (!wifiUp) { vTaskDelay(pdMS_TO_TICKS(200)); continue; }
        if (myGen != netGen) {
            myGen = netGen;
            tcpServer.end();
            tcpServer.begin();
        }
        WiFiClient c = tcpServer.accept();
        if (!c) { vTaskDelay(pdMS_TO_TICKS(20)); continue; }
        tcpSessions++;
        c.setNoDelay(true);
        while (c.connected() && wifiUp) {
            size_t n = c.write(buf, sizeof(buf));
            if (n == 0) break;
            tcpBytes += n;
        }
        c.stop();
    }
}

// ---------------------------------------------------------------- BLE
class ServerCb : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* s, NimBLEConnInfo& ci) override {
        bleConnected = true; bleConns++;
        s->updateConnParams(ci.getConnHandle(), 24, 48, 0, 180);   // same as sketch.ino
        Serial.printf("# ble connected peer=%s\n", ci.getAddress().toString().c_str());
    }
    void onDisconnect(NimBLEServer* s, NimBLEConnInfo& ci, int reason) override {
        bleConnected = false; bleSubscribed = false;
        if (bleActive) bleDisc++;
        Serial.printf("# ble disconnected reason=0x%X counted=%d\n", reason, (int)bleActive);
        if (bleActive) NimBLEDevice::startAdvertising();
    }
} serverCb;

class CharCb : public NimBLECharacteristicCallbacks {
    void onSubscribe(NimBLECharacteristic*, NimBLEConnInfo&, uint16_t sub) override {
        bleSubscribed = (sub != 0);
        if (bleSubscribed) bleSeq = 0;   // the app's loss counter assumes seq restarts on subscribe
        Serial.printf("# ble notify %s\n", bleSubscribed ? "subscribed" : "unsubscribed");
    }
} charCb;

static void bleStart()
{
    NimBLEDevice::init(BLE_NAME);
    bleServer = NimBLEDevice::createServer();
    bleServer->setCallbacks(&serverCb);
    NimBLEService* svc = bleServer->createService(ECG_SERVICE_UUID);
    bleChr = svc->createCharacteristic(ECG_CHAR_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
    bleChr->setCallbacks(&charCb);
    svc->start();
    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    adv->setName(BLE_NAME);
    adv->addServiceUUID(svc->getUUID());
    adv->enableScanResponse(true);
    adv->start();
    Serial.printf("# ble advertising name=%s\n", BLE_NAME);
}

// Synthetic ECG-like beat at 75 bpm, in raw counts on the scale the app expects.
static int32_t synth(uint32_t n)
{
    float t = fmodf((float)n / BLE_SPS, 0.8f);
    auto g = [](float t, float c, float w) { float x = (t - c) / w; return expf(-x * x); };
    return (int32_t)(150 * g(t, 0.10f, 0.025f)      // P
                   - 200 * g(t, 0.185f, 0.008f)     // Q
                   + 1800 * g(t, 0.20f, 0.010f)     // R
                   - 350 * g(t, 0.215f, 0.008f)     // S
                   + 350 * g(t, 0.45f, 0.040f));    // T
}

// Produces samples on the 256 SPS clock and notifies in 6-sample batches -
// the same cadence the ring firmware uses (~23.4 ms per packet).
static void bleTask(void*)
{
    uint8_t batch[2 + BLE_BATCH * 3];
    uint8_t slot = 0;
    uint32_t n = 0;
    int64_t t0 = esp_timer_get_time();

    for (;;) {
        uint32_t due = (uint32_t)((esp_timer_get_time() - t0) * BLE_SPS / 1000000);
        while (n < due) {
            int32_t v = synth(n++);
            uint8_t* d = &batch[2 + slot * 3];
            d[0] = v & 0xFF; d[1] = (v >> 8) & 0xFF; d[2] = (v >> 16) & 0xFF;
            if (++slot == BLE_BATCH) {
                if (bleActive && bleSubscribed) {
                    batch[0] = bleSeq++;
                    batch[1] = BLE_BATCH;
                    bleChr->setValue(batch, sizeof(batch));
                    if (bleChr->notify()) blePkts++; else bleNotifyFail++;
                }
                slot = 0;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

static void bleSetActive(bool on)
{
    bleActive = on;
    if (on) {
        NimBLEDevice::startAdvertising();
    } else {
        NimBLEDevice::stopAdvertising();
        for (uint16_t h : bleServer->getPeerDevices()) bleServer->disconnect(h);
    }
    Serial.printf("# ble active=%d\n", (int)on);
}

// ---------------------------------------------------------------- status
static void printStatus()
{
    int rssi = wifiUp ? WiFi.RSSI() : 0;
    if (wifiUp) { if (rssi < rssiMin) rssiMin = rssi; if (rssi > rssiMax) rssiMax = rssi; }
    uint32_t outageNow = wifiDownSinceMs ? millis() - wifiDownSinceMs : 0;
    Serial.printf("# st t=%lu ip=%s tx_dbm=%.1f wifi_on=%d wifi=%d rssi=%d rssi_min=%d rssi_max=%d disc=%lu last_reason=%lu "
                  "outage_ms=%lu longest_outage_ms=%lu udp_echoed=%lu tcp_sessions=%lu tcp_kb=%llu "
                  "ble_on=%d ble_conn=%d ble_sub=%d ble_conns=%lu ble_disc=%lu ble_pkts=%lu ble_fail=%lu "
                  "heap=%lu min_heap=%lu boots=%lu brownouts=%lu abnormal=%lu\n",
                  millis() / 1000, wifiUp ? WiFi.localIP().toString().c_str() : "-",
                  WiFi.getTxPower() / 4.0f, (int)wifiActive, (int)wifiUp, rssi, wifiUp || rssiMax > -127 ? rssiMin : 0,
                  rssiMax, wifiDisc, wifiLastReason, outageNow, wifiLongestOutageMs, udpEchoed,
                  tcpSessions, (unsigned long long)(tcpBytes / 1024), (int)bleActive, (int)bleConnected,
                  (int)bleSubscribed, bleConns, bleDisc, blePkts, bleNotifyFail,
                  ESP.getFreeHeap(), ESP.getMinFreeHeap(), boots, brownouts, abnormal);
}

// ---------------------------------------------------------------- main
void setup()
{
    Serial.begin(SERIAL_BAUD);
    delay(200);
    bootReport();

    WiFi.onEvent(onWifiEvent);
    wifiStart();
    bleStart();

    xTaskCreate(tcpTask, "tcp", 4096, nullptr, 1, nullptr);
    xTaskCreate(bleTask, "blegen", 4096, nullptr, 2, nullptr);
}

void loop()
{
    // UDP echo: the laptop sends [seq][send time], we send the same bytes back.
    // Restart the socket after every reconnect (a new IP invalidates it).
    static uint32_t udpGen = 0;
    if (wifiUp && udpGen != netGen) { udpGen = netGen; udp.stop(); udp.begin(UDP_ECHO_PORT); }
    if (wifiUp) {
        int len = udp.parsePacket();
        if (len > 0) {
            static uint8_t pkt[1472];
            int n = udp.read(pkt, sizeof(pkt));
            udp.beginPacket(udp.remoteIP(), udp.remotePort());
            udp.write(pkt, n);
            udp.endPacket();
            udpEchoed++;
        }
    }

    if (Serial.available()) {
        int c = Serial.read();
        if (c == 'w') {
            wifiActive = !wifiActive;
            if (wifiActive) wifiStart();
            else { WiFi.disconnect(true); WiFi.mode(WIFI_OFF); wifiUp = false; wifiDownSinceMs = 0; }
            Serial.printf("# wifi active=%d\n", (int)wifiActive);
        } else if (c == 'b') {
            bleSetActive(!bleActive);
        } else if (c == 's') {
            printStatus();
        } else if (c == 'p' && wifiActive) {
            txStep = (txStep + 1) % (int)(sizeof(kTxSteps) / sizeof(kTxSteps[0]));
            WiFi.disconnect(false);
            WiFi.setTxPower(kTxSteps[txStep]);
            WiFi.begin(WIFI_SSID, WIFI_PASS);
            WiFi.setTxPower(kTxSteps[txStep]);
            Serial.printf("# txpower set_dbm=%.1f\n", WiFi.getTxPower() / 4.0f);
        } else if (c == 'n' && wifiActive) {
            WiFi.disconnect(false);
            scanReport();
            WiFi.begin(WIFI_SSID, WIFI_PASS);
        }
    }

    static uint32_t lastStatus = 0;
    if (millis() - lastStatus >= STATUS_MS) { lastStatus = millis(); printStatus(); }
    delay(1);
}
