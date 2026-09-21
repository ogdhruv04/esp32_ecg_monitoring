// SPDX-License-Identifier: MIT
/**
 * @file sketch.ino
 * @brief ECG stream example that prints raw MAX30003 ECG samples to Serial.
 *
 * Adapted from ProtoCentral's "02-ecg-plotter" example (Arduino Uno pin
 * numbers replaced with the ESP32-C3 SuperMini's default hardware SPI pins).
 * Confirm CS_PIN against your actual PCB wiring before flashing.
 *
 * ESP32-C3 default hardware SPI pins (from arduino-esp32 pins_arduino.h):
 *  - MISO : GPIO5
 *  - MOSI : GPIO6
 *  - SCLK : GPIO4
 *  - CS   : GPIO7 (default SS; change CS_PIN below if wired elsewhere)
 *  - VCC  : 3.3V
 *  - GND  : GND
 * - INT1  : GPIO10 
 */

#include <SPI.h>
#include "protocentral_max30003.h"
#include <NimBLEDevice.h>

// ---------------------------------------------------------------------------
// Board configuration
//
// ONE source file drives both devices on purpose. The whole point of the
// two-device study is that the only difference between them is where the
// electrodes sit - so the decoding, the register config, the sample rate and
// the timestamping must be byte-identical. Fork this file and they stop being
// comparable.
// ---------------------------------------------------------------------------
#if CONFIG_IDF_TARGET_ESP32C3
  // RING device - ESP32-C3 SuperMini, native USB-CDC.
  // SPI uses the C3's FSPI defaults: SCK=4, MISO=5, MOSI=6.
  #define DEVICE_TAG          "RING"
  #define MAX30003_CS_PIN     7
  #define MAX30003_INT1_PIN   10
  #define SYNC_PIN            3
  #define ENABLE_BLE          1
#else
  // REFERENCE device - ESP32-WROOM-32, USB-UART bridge.
  // SPI uses the classic ESP32's VSPI defaults, which the schematic matches
  // exactly: SCK=IO18, MISO=IO19, MOSI=IO23, and CS=IO5 (also the default).
  // We pass CS explicitly anyway.
  #define DEVICE_TAG          "REF"
  #define MAX30003_CS_PIN     5     // VERIFIED by SPI scan: INFO reads 0x513261 with
                                    // CS on IO5. I first read IO4 off the
                                    // schematic and it was wrong - the label
                                    // sits a row off. Measured, not read.
  #define MAX30003_INT1_PIN   15    // schematic: INTB -> IO15
  #define SYNC_PIN            25    // free on the schematic; IO27 is GSRSENSE, IO12 is a
                                    // strapping pin, so 25 is the safe spare
  #define ENABLE_BLE          0     // a transmitter next to the AFE is noise we don't need
#endif

// Serial rate. On the C3 this is ignored - native USB-CDC runs at USB speed
// regardless. On the WROOM board it is a real UART through a bridge chip, and
// it matters: one CSV line is ~28 bytes, so 256 SPS needs ~7.2 kB/s = ~72 kbit/s
// before overhead. The 57600 we used on the C3 is BELOW that and would drop
// lines or stall the loop into a FIFO overflow.
#define SERIAL_BAUD 460800

// Set to 0 once the interrupt pin is confirmed.
#define INTB_SCAN 0

MAX30003 max30003(MAX30003_CS_PIN);

// ---------------------------------------------------------------------------
// ECG FIFO decoding
//
// The ECG FIFO word is NOT a 24-bit sample. It packs three fields:
//   bits [23:6] = 18-bit signed ECG sample
//   bits [5:3]  = ETAG (status)
//   bits [2:0]  = PTAG (pace)
// The library's readEcgSample() returns the whole word sign-extended from
// bit 23, i.e. (sample * 64 + tags), and never inspects ETAG - so an
// overflowed FIFO reads as plausible-looking data. We decode it ourselves.
// ---------------------------------------------------------------------------
enum : uint8_t {
    // Datasheet Rev 3, p.42 Table 33.
    ETAG_VALID     = 0,  // valid sample
    ETAG_FAST      = 1,  // fast-recovery mode: time step valid, VOLTAGE NOT VALID
    ETAG_VALID_EOF = 2,  // valid, last sample in FIFO
    ETAG_FAST_EOF  = 3,  // fast mode, last in FIFO: time valid, VOLTAGE NOT VALID
    ETAG_EMPTY     = 6,  // FIFO empty
    ETAG_OVERFLOW  = 7   // FIFO overflowed - must FIFO_RST to recover
};

struct EcgWord {
    int32_t sample;
    uint8_t etag;
    uint8_t ptag;
};

static bool readEcgWord(EcgWord& w)
{
    uint8_t b[3] = {0};
    if (!max30003.readRegister(REG_ECG_FIFO, b, 3)) return false;

    uint32_t raw = ((uint32_t)b[0] << 16) | ((uint32_t)b[1] << 8) | b[2];

    int32_t s = (int32_t)(raw >> 6);          // bits [23:6]
    if (s & 0x20000) s |= ~0x3FFFF;           // sign-extend from bit 17

    w.sample = s;
    w.etag = (raw >> 3) & 0x07;
    w.ptag = raw & 0x07;
    return true;
}

// Sample rate. The MAX30003 ADC is the clock for this whole system: with zero
// dropped samples, sampleIndex/ECG_SPS *is* the timestamp, and it is far more
// stable than anything micros() can give us. The micros() values we log exist
// to *verify* that assumption (measure jitter, confirm the true rate), not to
// serve as the time base. See PLAN Part 0.
#define ECG_SPS 256

// Diagnostics - the evidence that the fix works.
uint32_t statValid = 0, statOverflow = 0, statEmpty = 0, statOther = 0;
uint32_t sampleIndex = 0;   // monotonic; gaps mean lost samples
uint32_t lastStatsMs = 0;

// Lifetime counters (never cleared) - these are the gate numbers.
uint32_t lifeValid = 0, lifeOverflow = 0, lifeDropped = 0;

// FIFO headroom. The FIFO is 32 deep; how close we run to that is the margin
// between "working" and the silent overflow that invalidated our earlier data.
uint8_t  maxDrainDepth = 0;
uint32_t lastStatus = 0;
uint32_t statSweeps = 0;
uint32_t lastServiceMs = 0;

// ISR timing. lastIsrMicros is captured in the ISR itself, so it timestamps the
// FIFO-threshold event rather than whenever loop() got around to servicing it.
volatile uint32_t lastIsrMicros = 0;
uint32_t prevIsrMicros = 0;
uint32_t isrGapMin = 0xFFFFFFFF, isrGapMax = 0;

// INT1 fires when the FIFO reaches its threshold. The ISR only raises a flag;
// all SPI traffic happens in loop(). Replaces the old free-running delay(8),
// which consumed slower than the sensor produced and silently overflowed the
// FIFO after ~10s.
volatile bool ecgIntFlag = false;
// Sync marker. Two ESP32s have unrelated clocks that also drift (crystal
// tolerance ~10-20 ppm is ~6 ms over 5 minutes), so a shared electrical event
// is what lets their two recordings be put on one timeline. Wire SYNC_PIN of
// both devices to the same signal; each logs the sample index it saw the edge
// at, and the offset between those indices aligns the streams. RR intervals are
// differences, so a constant offset cancels - what this pins down is the
// residual rate mismatch.
volatile uint32_t syncMicros = 0;
volatile uint32_t syncCount = 0;
void IRAM_ATTR syncIsr() { syncMicros = micros(); syncCount++; }

volatile uint32_t isrCount = 0;
void IRAM_ATTR ecgIsr() { lastIsrMicros = micros(); isrCount++; ecgIntFlag = true; }

// BLE ECG service: streams batches of 6 raw 24-bit samples per notification.
// Packet layout (20 bytes): [seq][count=6][6 x 3-byte little-endian samples]
// Batched (rather than 1 sample/notification) to land in the default 20-byte
// ATT payload with no MTU negotiation, at a cadence close to a typical
// Android connection interval (~30-50ms) instead of asking for one
// notification every 8ms.
static const char* ECG_SERVICE_UUID = "e54b0001-67f5-479e-8711-b3b99198ce6c";
static const char* ECG_CHAR_UUID    = "e54b0002-67f5-479e-8711-b3b99198ce6c";
#define ECG_BATCH_SIZE 6

NimBLEServer* pServer = nullptr;
NimBLECharacteristic* pEcgChr = nullptr;
volatile bool ecgSubscribed = false;
uint8_t ecgSeq = 0;

class EcgServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* server, NimBLEConnInfo& connInfo) override {
        Serial.println("BLE client connected");
        // Request a tighter connection interval (30-60ms) to reduce notification
        // drops under our ~48ms batch cadence; the peer may not honor it exactly.
        server->updateConnParams(connInfo.getConnHandle(), 24, 48, 0, 180);
    }
    void onDisconnect(NimBLEServer* server, NimBLEConnInfo& connInfo, int reason) override {
        Serial.println("BLE client disconnected, restarting advertising");
        ecgSubscribed = false;
        NimBLEDevice::startAdvertising();
    }
} ecgServerCallbacks;

class EcgCharCallbacks : public NimBLECharacteristicCallbacks {
    void onSubscribe(NimBLECharacteristic* chr, NimBLEConnInfo& connInfo, uint16_t subValue) override {
        ecgSubscribed = (subValue != 0);
        // Restart the sequence numbering on every fresh subscribe. ecgSeq is
        // incremented for every batch whether or not anyone is listening, so it
        // free-runs during scan, connect and any disconnected stretch. The peer
        // then sees its first packet arrive with an arbitrary seq and every gap
        // since boot looks like packet loss - we measured a reported 91.75% loss
        // on a link that was in fact dropping nothing at all.
        if (ecgSubscribed) ecgSeq = 0;
        Serial.printf("BLE notify %s\n", ecgSubscribed ? "subscribed" : "unsubscribed");
    }
} ecgCharCallbacks;

void setupBle()
{
#if !ENABLE_BLE
    return;   // reference device: radio stays off
#else
    NimBLEDevice::init("ESP32-ECG");

    pServer = NimBLEDevice::createServer();
    pServer->setCallbacks(&ecgServerCallbacks);

    NimBLEService* pService = pServer->createService(ECG_SERVICE_UUID);
    pEcgChr = pService->createCharacteristic(ECG_CHAR_UUID,
        NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
    pEcgChr->setCallbacks(&ecgCharCallbacks);
    pService->start();

    NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
    pAdvertising->setName("ESP32-ECG");
    pAdvertising->addServiceUUID(pService->getUUID());
    pAdvertising->enableScanResponse(true);
    pAdvertising->start();

    Serial.println("BLE advertising started as ESP32-ECG");
#endif
}

// Packs `value`'s low 3 bytes (little-endian) into a 6-slot batch buffer;
// every 6th call, stamps seq/count and sends one 20-byte notification.
void sendEcgSampleOverBle(int32_t value)
{
#if !ENABLE_BLE
    (void)value; return;
#else
    static uint8_t batch[2 + ECG_BATCH_SIZE * 3];
    static uint8_t slot = 0;

    uint8_t* dst = &batch[2 + slot * 3];
    dst[0] = value & 0xFF;
    dst[1] = (value >> 8) & 0xFF;
    dst[2] = (value >> 16) & 0xFF;
    slot++;

    if (slot >= ECG_BATCH_SIZE) {
        if (ecgSubscribed) {
            batch[0] = ecgSeq++;
            batch[1] = ECG_BATCH_SIZE;
            pEcgChr->setValue(batch, sizeof(batch));
            pEcgChr->notify();
        }
        slot = 0;
    }
#endif
}

// The library's begin() never enables any interrupt, so INT1 (wired to GPIO10)
// stayed idle. Enable the ECG-FIFO and FIFO-overflow interrupts and set the
// FIFO threshold that drives them.
void setupEcgInterrupt()
{
    // EN_INT: EN_EINT (bit 23) | EN_EOVF (bit 22) | INTB_TYPE = 0b01 (CMOS
    // push-pull, active low).
    //
    // This started as 0b11 (open-drain + internal pullup), which is the
    // conventional choice and is what left INT1 dead. Measured on this board:
    // with INTB three-stated and every source disabled, GPIO10 still read LOW
    // against the ESP32's ~45k internal pullup - something on that net loads it
    // harder than the pullup can answer. In push-pull the part drives the
    // de-asserted level high itself and the pin reads 1 correctly. Nothing is
    // shared on this line, so there is no reason to want open-drain here.
    max30003.writeRegister(REG_EN_INT, 0xC00001);
    delay(10);

    // MNGR_INT: EFIT[4:0] in bits [23:19]. EFIT=3 -> assert once 4 samples are
    // queued. We drain the FIFO completely on each service regardless, so this
    // only sets how often we wake, not how much we read.
    max30003.writeRegister(REG_MNGR_INT, 0x180004);
    delay(10);

    pinMode(MAX30003_INT1_PIN, INPUT);

    // Drain and clear before arming: if INTB is already low when we attach a
    // FALLING-edge handler, the first edge never arrives.
    max30003.writeRegister(REG_FIFO_RST, 0x000000);
    uint8_t st[3];
    max30003.readRegister(REG_STATUS, st, 3);

    attachInterrupt(digitalPinToInterrupt(MAX30003_INT1_PIN), ecgIsr, FALLING);

#if INTB_SCAN
    { static const uint8_t c[] = {15,16,17,4,2,13,14,12,25,26,27,32,33};
      for (size_t i = 0; i < sizeof(c); i++) pinMode(c[i], INPUT); }
#endif

    pinMode(SYNC_PIN, INPUT_PULLDOWN);
    attachInterrupt(digitalPinToInterrupt(SYNC_PIN), syncIsr, RISING);

    uint8_t rb[3];
    max30003.readRegister(REG_EN_INT,   rb, 3);
    Serial.printf("# EN_INT   readback: %02X%02X%02X (wrote C00001)\n", rb[0], rb[1], rb[2]);
    max30003.readRegister(REG_MNGR_INT, rb, 3);
    Serial.printf("# MNGR_INT readback: %02X%02X%02X (wrote 180004)\n", rb[0], rb[1], rb[2]);
    max30003.readRegister(REG_CNFG_ECG, rb, 3);
    Serial.printf("# CNFG_ECG readback: %02X%02X%02X (rate bits [23:22])\n", rb[0], rb[1], rb[2]);
    max30003.readRegister(REG_STATUS,   rb, 3);
    Serial.printf("# STATUS   readback: %02X%02X%02X\n", rb[0], rb[1], rb[2]);
    Serial.printf("# INT1 pin GPIO%d reads %d (0 = asserted, open-drain active low)\n",
                  MAX30003_INT1_PIN, digitalRead(MAX30003_INT1_PIN));
}

// Emit one sample as a machine-parseable CSV record:
//   S,<index>,<isr_micros>,<value>,<etag>
// Lines starting with '#' are human-readable diagnostics, so a parser can split
// the two trivially.
//
// The availableForWrite() guard matters more than it looks. USB-CDC blocks once
// the host stops draining its buffer, and a blocked Serial.write() stalls loop()
// long enough to overflow the 32-deep FIFO - reintroducing, through the back
// door, the exact bug we just fixed. We would rather lose a log line than lose
// samples, so we count the drop and move on.
static inline void logSample(uint32_t idx, uint32_t us, int32_t value, uint8_t etag)
{
    // leadoff = STATUS[3:0] = LDOFF_PH | LDOFF_PL | LDOFF_NH | LDOFF_NL.
    //
    // These are bits [3:0], NOT [11:8]. This read the wrong nibble until now:
    // bits [11:8] are PLLINT/SAMP/RRINT/LONINT, so the "97% lead-off" we were
    // logging was actually the SAMP bit - a normal sample-timing flag that is
    // supposed to be set. Nothing gated on it, so no result depended on the
    // misreading, but every capture before this has a mislabelled column.
    //
    // DC lead-off detection is enabled by begin() (CNFG_GEN EN_DCLOFF, bits
    // [13:12] = 01), but IMAG (bits [10:8]) is left at 000, which the datasheet
    // (Rev 3, p.33) defines as "0nA - disable and disconnect current sources".
    // Do not treat this column as a contact indicator until an unplugged-
    // electrode test shows it firing.
    uint8_t leadoff = lastStatus & 0x0F;
    char line[56];
    int n = snprintf(line, sizeof(line), "S,%lu,%lu,%ld,%u,%u\n",
                     (unsigned long)idx, (unsigned long)us, (long)value, etag, leadoff);
    if (Serial.availableForWrite() >= n) Serial.write((const uint8_t*)line, n);
    else                                 lifeDropped++;
}

// Drain the FIFO until it reports empty or hands us the end-of-file marker.
// Draining fully is what actually prevents the overflow: it decouples our
// service rate from the sensor's sample rate.
void serviceEcgFifo()
{
    uint32_t us = lastIsrMicros;
    uint8_t drained = 0;

    for (int guard = 0; guard < 64; guard++) {   // bounded, never spin forever
        EcgWord w;
        if (!readEcgWord(w)) break;

        switch (w.etag) {
        case ETAG_VALID:
        case ETAG_FAST:
            statValid++; lifeValid++; sampleIndex++; drained++;
            logSample(sampleIndex, us, w.sample, w.etag);
            sendEcgSampleOverBle(w.sample);
            break;

        case ETAG_VALID_EOF:
        case ETAG_FAST_EOF:
            statValid++; lifeValid++; sampleIndex++; drained++;
            logSample(sampleIndex, us, w.sample, w.etag);
            sendEcgSampleOverBle(w.sample);
            goto done;                           // that was the last one

        case ETAG_EMPTY:
            statEmpty++;
            goto done;

        case ETAG_OVERFLOW:
            statOverflow++; lifeOverflow++;
            max30003.writeRegister(REG_FIFO_RST, 0x000000);
            goto done;                           // samples after this are lost

        default:
            statOther++;
            goto done;
        }
    }
done:
    if (drained > maxDrainDepth) maxDrainDepth = drained;

    // Clear the latched interrupt bits.
    //
    // EINT de-asserts on its own once the FIFO drops below the EFIT threshold.
    // EOVF does NOT clear on a STATUS read: it stays asserted until FIFO_RST or
    // SYNCH (datasheet Rev 3, p.26 Table 8), which is why the overflow case above
    // issues FIFO_RST. Reading STATUS here clears the terms that are cleared by
    // read-back (DCLOFFINT, LONINT, PLLINT, and the LDOFF detail bits) and
    // captures the lead-off bits for logging.
    //
    // (INT1 being dead was a separate problem: open-drain INTB could not pull
    // the line back high on this board. See setupEcgInterrupt().)
    uint8_t st[3];
    max30003.readRegister(REG_STATUS, st, 3);
    lastStatus = ((uint32_t)st[0] << 16) | ((uint32_t)st[1] << 8) | st[2];
}

void setup()
{
    Serial.begin(SERIAL_BAUD);

    setupBle();

    pinMode(MAX30003_CS_PIN,OUTPUT);
    digitalWrite(MAX30003_CS_PIN,HIGH); //disable device

    SPI.begin();

    bool ret = max30003.readDeviceID();
    if(ret){
      Serial.println("Max30003 read ID Success");
    }else{

      while(!ret){
        //stay here untill the issue is fixed.
        uint8_t buf[3] = {0};
        max30003.readRegister(REG_INFO, buf, 3);
        Serial.printf("Failed to read ID. Raw INFO reg (expect 0x5_ 0x__ 0x__): 0x%02X 0x%02X 0x%02X\n", buf[0], buf[1], buf[2]);
        ret = max30003.readDeviceID();
        delay(2000);
      }
    }

    Serial.println("Initialising the chip ...");
    max30003.begin();   // initialize MAX30003

    // begin() hardcodes CNFG_ECG = 0x805000 -> RATE bits [23:22] = 0b10 = 128 SPS.
    // 128 SPS quantizes RR intervals at 7.8 ms, which is coarse next to RMSSD
    // values of 20-50 ms. 256 SPS halves that to 3.9 ms. setSamplingRate() does a
    // read-modify-write, so the 0.5 Hz HPF / 40 Hz LPF / gain bits are preserved.
    if (max30003.setSamplingRate(SR_256)) Serial.printf("# sample rate set to %d SPS\n", ECG_SPS);
    else                                  Serial.println("# WARNING: setSamplingRate failed");
    delay(50);

    setupEcgInterrupt();
    max30003.writeRegister(REG_FIFO_RST, 0x000000);  // start from a clean FIFO
    lastStatsMs = millis();
    Serial.println("# fmt: S,index,isr_micros,value,etag,leadoff");
    Serial.println("# fmt: K,sync_count,sync_micros,sample_index");
    Serial.printf("# device: %s  cs=%d int1=%d sync=%d ble=%d sps=%d\n",
                  DEVICE_TAG, MAX30003_CS_PIN, MAX30003_INT1_PIN,
                  SYNC_PIN, ENABLE_BLE, ECG_SPS);
}

// Runtime toggle for the body-bias generator, so we can A/B it without
// reflashing (this board needs a manual BOOT+EN dance for every flash).
//
// The library's begin() writes CNFG_GEN = 0x081007. Decoding that: RBIASP and
// RBIASN are connected and RBIASV is 100 MOhm, but EN_RBIAS (bits [5:4]) is 00
// - DISABLED. So the bias inputs are wired up with nothing driving them. An
// unbiased body floats and couples mains readily, and we measure 94.7% of raw
// power at 50 Hz with electrodes attached versus 1.0% with them off. This is
// the obvious suspect.
void setRbias(bool on)
{
    uint8_t b[3] = {0};
    max30003.readRegister(REG_CNFG_GEN, b, 3);
    uint32_t v = ((uint32_t)b[0] << 16) | ((uint32_t)b[1] << 8) | b[2];
    v = (v & ~0x000030UL) | (on ? 0x000010UL : 0x000000UL);   // EN_RBIAS[5:4]
    max30003.writeRegister(REG_CNFG_GEN, v);
    delay(20);
    max30003.readRegister(REG_CNFG_GEN, b, 3);
    Serial.printf("# EN_RBIAS %s -> CNFG_GEN now %02X%02X%02X\n",
                  on ? "ON" : "OFF", b[0], b[1], b[2]);
}

void loop()
{
    // 'b' toggles body bias, 'r' resets the FIFO.
    if (Serial.available()) {
        int c = Serial.read();
        if (c == 'b') { static bool rb = false; rb = !rb; setRbias(rb); }
        else if (c == 'r') { max30003.writeRegister(REG_FIFO_RST, 0x000000); }
    }

    if (ecgIntFlag) {
        ecgIntFlag = false;
        // Gap between consecutive FIFO-threshold interrupts. With EFIT=3 the
        // sensor asserts every 4 samples, so at 256 SPS this should be ~15625 us.
        // Spread between min and max is our timing jitter, measured rather than
        // assumed.
        uint32_t now = lastIsrMicros;
        if (prevIsrMicros) {
            uint32_t gap = now - prevIsrMicros;
            if (gap < isrGapMin) isrGapMin = gap;
            if (gap > isrGapMax) isrGapMax = gap;
        }
        prevIsrMicros = now;
        serviceEcgFifo();
        lastServiceMs = millis();
    }

    // Safety net: if interrupts ever stop arriving the FIFO would fill silently,
    // so sweep it if the ISR has gone quiet. Gated on ISR silence rather than
    // running unconditionally - a free-running 100 ms sweep drains the FIFO out
    // from under the interrupt, which resets the EFIT count and shows up as
    // interrupt gaps of 6 sample periods instead of 4. Now it fires only when
    // it is actually needed.
    if (millis() - lastServiceMs >= 250) {
        lastServiceMs = millis();
        statSweeps++;
        serviceEcgFifo();
    }

    // Emit sync markers as their own line type so the parser can pick them out
    // without disturbing the sample stream.
    static uint32_t lastSyncSeen = 0;
    if (syncCount != lastSyncSeen) {
        lastSyncSeen = syncCount;
        Serial.printf("K,%lu,%lu,%lu\n",
                      (unsigned long)lastSyncSeen,
                      (unsigned long)syncMicros,
                      (unsigned long)sampleIndex);
    }

#if INTB_SCAN
    // INTB pin discovery. CS was misread off the schematic once already, so the
    // interrupt pin is not trusted either. Once the sensor is configured, INTB
    // pulses at ECG_SPS/4 (~64 Hz), which is unmistakable: any candidate that is
    // observed both high AND low during normal operation is a live signal.
    // Sampled inside the normal loop rather than a tight poll - a blocking poll
    // stops the FIFO draining, INTB latches asserted, and a working pin would
    // look dead.
    static const uint8_t kCand[] = {15, 16, 17, 4, 2, 13, 14, 12, 25, 26, 27, 32, 33};
    static bool sawHi[sizeof(kCand)] = {false}, sawLo[sizeof(kCand)] = {false};
    static bool scanDone = false;
    if (!scanDone) {
        for (size_t i = 0; i < sizeof(kCand); i++) {
            if (digitalRead(kCand[i])) sawHi[i] = true; else sawLo[i] = true;
        }
        if (millis() > 6000) {
            scanDone = true;
            Serial.print("# INTB scan - pins seen toggling: ");
            bool any = false;
            for (size_t i = 0; i < sizeof(kCand); i++)
                if (sawHi[i] && sawLo[i]) { Serial.printf("IO%d ", kCand[i]); any = true; }
            Serial.println(any ? "" : "(none)");
        }
    }
#endif

    if (millis() - lastStatsMs >= 5000) {
        uint32_t elapsed = millis() - lastStatsMs;
        lastStatsMs = millis();
        // rate_x100 is the measured sample rate; it should sit on ECG_SPS. If it
        // reads low, we are losing samples somewhere even with a clean ETAG count.
        uint32_t rate_x100 = (uint32_t)((uint64_t)statValid * 100000ULL / elapsed);
        Serial.printf("# 5s: valid:%lu ovf:%lu empty:%lu other:%lu rate:%lu.%02lu "
                      "| life: valid:%lu ovf:%lu logdrop:%lu depth_max:%u/32 "
                      "isr:%lu sweep:%lu pin:%d status:%06lX isr_gap_us:%lu-%lu\n",
                      statValid, statOverflow, statEmpty, statOther,
                      rate_x100 / 100, rate_x100 % 100,
                      lifeValid, lifeOverflow, lifeDropped, maxDrainDepth,
                      isrCount, statSweeps, digitalRead(MAX30003_INT1_PIN), lastStatus,
                      isrGapMin == 0xFFFFFFFF ? 0 : isrGapMin, isrGapMax);
        statValid = statOverflow = statEmpty = statOther = 0;
        isrGapMin = 0xFFFFFFFF; isrGapMax = 0;
    }
}
