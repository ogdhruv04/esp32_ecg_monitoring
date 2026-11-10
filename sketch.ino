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
#include <Wire.h>
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
#if defined(BOARD_TEST_C3)
  // TEST device - custom ESP32-C3 board (docs/ESP32C3_custom_schematic.pdf),
  // FTDI on UART0, built by build_test.sh. Not part of the two-device study.
  // GPIO10 is not on its header, so INTB is wired to GPIO3 and SYNC takes
  // GPIO10 instead (unconnected; the pulldown keeps it quiet).
  #define DEVICE_TAG          "TEST"
  #define MAX30003_CS_PIN     7
  #define MAX30003_INT1_PIN   3
  #define SYNC_PIN            10
  #define ENABLE_BLE          1     // advertises as ESP32-ECG, same as the ring:
                                    // power only one of the two near the phone
  #define SENS_SDA_PIN        -1    // no extra sensors on this board
  #define SENS_SCL_PIN        -1
  #define GSR_ADC_PIN         -1
#elif CONFIG_IDF_TARGET_ESP32C3
  // RING device - ESP32-C3 SuperMini, native USB-CDC.
  // SPI uses the C3's FSPI defaults: SCK=4, MISO=5, MOSI=6.
  #define DEVICE_TAG          "RING"
  #define MAX30003_CS_PIN     7
  #define MAX30003_INT1_PIN   10
  #define SYNC_PIN            3
  #define ENABLE_BLE          1
  #define SENS_SDA_PIN        -1    // no extra sensors on this board
  #define SENS_SCL_PIN        -1
  #define GSR_ADC_PIN         -1
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
  // Extra sensors, from docs/ESP32_health_schematic.pdf (docs/sensor_inventory.md).
  // Read by module pin number, not by where the net label sits: SDA is on
  // module pin 33 = IO21, SCL on pin 36 = IO22, GSRSENSE on pin 12 = IO27.
  // NOT YET CONFIRMED ON THE BOARD - the boot probe line is the confirmation.
  #define SENS_SDA_PIN        21    // MAX30102 + MAX30205 + MPU6050 share this bus
  #define SENS_SCL_PIN        22
  #define GSR_ADC_PIN         27    // ADC2_CH7; usable because WiFi is never started
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

// One I2C sensor's bookkeeping (see "Extra sensors" below). Declared up here,
// ahead of the first function, so arduino-cli's generated prototypes see it.
struct SensorStat {
    bool     present;   // answered the boot probe and has not been disabled since
    uint8_t  addr;      // 7-bit I2C address in use
    uint8_t  errRun;    // consecutive failed transactions
    uint32_t errs;      // lifetime failed transactions
    uint32_t n;         // samples acquired = the sequence number of the last line
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

// ---------------------------------------------------------------------------
// Extra sensors: MAX30102 (PPG), MPU6050 (IMU) and MAX30205 (temperature) on
// one I2C bus, and the GSR front end on an ADC pin. Board, pins and the open
// questions are in docs/sensor_inventory.md; every register value below is
// checked against the datasheets in docs/sensor_datasheet_check.md.
//
// This code is compiled for every board and is switched by the pin block at
// the top (-1 = not wired), never by a per-board fork. It runs strictly AFTER
// the ECG FIFO has been drained, never instead of it, and it may not block:
// a sensor that stops answering is dropped after SENS_ERR_LIMIT failures.
//
// Timestamps. Every sensor line carries two clocks:
//   ecg_index  the index of the newest ECG sample drained when the reading
//              was taken. This is the timestamp on the ECG clock, but it only
//              advances in steps of one FIFO drain (4 samples, 15.6 ms).
//   micros     the ESP32's micros() at the reading. The S lines carry the same
//              clock (isr_micros), so the host can place a reading between two
//              ECG samples by fitting micros against index over the capture.
// IMU, GSR and temperature are sampled ON the ECG clock: one reading every
// IMU_EVERY / GSR_EVERY / TEMP_EVERY ECG samples, right after the drain that
// crossed the boundary. The MAX30102 cannot be: it free-runs on its own
// oscillator at PPG_SPS and queues samples in its own FIFO. So P lines carry
// ppg_index, the MAX30102's own sample count (its clock, as the ECG index is
// the MAX30003's), and the ecg_index/micros of the poll that fetched them.
// A sample was taken at or before that poll, never after, so the earliest
// polls trace the true ppg_index -> ECG time line.
//
// Line formats (all integers):
//   P,ppg_index,ecg_index,micros,red,ir          18-bit counts, MAX30102 clock
//   M,seq,ecg_index,micros,ax,ay,az,gx,gy,gz     int16; 16384 LSB/g, 131 LSB/(deg/s)
//   T,seq,ecg_index,micros,raw                   int16; 0.00390625 degC per LSB
//   G,seq,ecg_index,micros,adc_sum,mv_sum        sums of GSR_OVERSAMPLE reads
// seq counts readings TAKEN, so a hole in seq on the host is a line lost on
// the way (or dropped here: see sensLogDropped), while a jump in ecg_index at
// an unbroken seq is a reading that was taken late.
// ---------------------------------------------------------------------------
#define MAX30102_ADDR     0x57    // fixed (write 0xAE / read 0xAF)
#define MAX30205_ADDR     0x48    // A2 = A1 = A0 = GND on the schematic -> 0x90 >> 1
#define MPU6050_ADDR_LO   0x68    // AD0 low
#define MPU6050_ADDR_HI   0x69    // AD0 high; AD0 only reaches a header on this board

#define PPG_SPS           100     // MAX30102 SPO2_SR = 001
#define IMU_EVERY         4       // ECG samples per IMU reading   -> 64 Hz
#define GSR_EVERY         16      //                               -> 16 Hz
#define TEMP_EVERY        256     //                               ->  1 Hz
#define GSR_OVERSAMPLE    8
#define PPG_MAX_PER_READ  8       // 48 bytes; the Wire buffer holds 128
#define SENS_ERR_LIMIT    8
#define SENS_I2C_TIMEOUT_MS 10    // a hung bus must not outlast the ECG FIFO

// Sensor lines never take the last SENS_TX_RESERVE bytes of the transmit
// buffer: that room is kept for the ECG batch that follows. An S line is lost
// only when the buffer is completely full; a sensor line gives way first.
#define SERIAL_TX_BUFFER  4096
#define SENS_TX_RESERVE   256

static SensorStat ppg  = {false, MAX30102_ADDR,   0, 0, 0};
static SensorStat imu  = {false, MPU6050_ADDR_LO, 0, 0, 0};
static SensorStat temp = {false, MAX30205_ADDR,   0, 0, 0};
static bool     gsrOn = false;
static uint32_t gsrN = 0;
static bool     sensBusUp = false;
static uint32_t sensI2cHz = 400000;       // 'f' toggles 400 k / 100 k
static uint8_t  ppgLedPa = 0x1F;          // 'p' steps it; 0x1F = 6.2 mA typical (p.20)
static uint8_t  ppgPartId = 0, imuWhoAmI = 0;
static uint32_t ppgFifoLost = 0;          // samples the MAX30102 FIFO overflowed
static uint32_t sensLogDropped = 0;       // sensor lines dropped on a full TX buffer

static bool i2cReadReg(uint8_t addr, uint8_t reg, uint8_t *buf, size_t n)
{
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(addr, n, true) != n) return false;
    for (size_t i = 0; i < n; i++) buf[i] = (uint8_t)Wire.read();
    return true;
}

static bool i2cWriteReg(uint8_t addr, uint8_t reg, uint8_t val)
{
    Wire.beginTransmission(addr);
    Wire.write(reg);
    Wire.write(val);
    return Wire.endTransmission(true) == 0;
}

static void sensFail(SensorStat& s, const char *name)
{
    s.errs++;
    if (++s.errRun >= SENS_ERR_LIMIT) {
        s.present = false;
        Serial.printf("# sens %s: DISABLED after %d consecutive I2C errors at ecg_index %lu "
                      "(send 'i' to probe again)\n",
                      name, SENS_ERR_LIMIT, (unsigned long)sampleIndex);
    }
}

static inline void logSensorLine(const char *line, int n)
{
    if (Serial.availableForWrite() >= n + SENS_TX_RESERVE) Serial.write((const uint8_t*)line, n);
    else                                                   sensLogDropped++;
}

// MAX30102, datasheet 19-7740 Rev 1. SpO2 mode = red + IR (p.18), 100 samples/s
// (p.19), 411 us pulses = 18-bit (p.19; allowed together, p.23 Table 11), ADC
// full scale 4096 nA (p.18), no on-chip averaging and FIFO_ROLLOVER_EN = 0
// (p.17) so a full FIFO loses the NEWEST samples and OVF_COUNTER counts them
// (p.13) - the loss is then visible as a jump in ppg_index instead of silent.
// Its INT pin is not routed to the ESP32, so the FIFO is polled.
static bool initPpg()
{
    uint8_t id = 0, rev = 0, rb[6] = {0};
    ppg.present = false;
    if (!i2cReadReg(MAX30102_ADDR, 0xFF, &id, 1)) {
        Serial.println("# sens ppg: no answer at 0x57 (MAX30102 absent, or HR1 jumper open)");
        return false;
    }
    ppgPartId = id;
    i2cReadReg(MAX30102_ADDR, 0xFE, &rev, 1);
    i2cWriteReg(MAX30102_ADDR, 0x09, 0x40);                 // RESET; self-clearing (p.18)
    for (int i = 0; i < 20; i++) {
        uint8_t m = 0x40;
        delay(1);
        if (i2cReadReg(MAX30102_ADDR, 0x09, &m, 1) && !(m & 0x40)) break;
    }
    bool ok = true;
    ok &= i2cWriteReg(MAX30102_ADDR, 0x08, 0x00);           // FIFO: SMP_AVE 1, no rollover
    ok &= i2cWriteReg(MAX30102_ADDR, 0x0A, 0x27);           // 4096 nA, 100 sps, 411 us
    ok &= i2cWriteReg(MAX30102_ADDR, 0x0C, ppgLedPa);       // LED1 = red (p.21)
    ok &= i2cWriteReg(MAX30102_ADDR, 0x0D, ppgLedPa);       // LED2 = IR
    ok &= i2cWriteReg(MAX30102_ADDR, 0x04, 0x00);           // FIFO_WR_PTR  } cleared before
    ok &= i2cWriteReg(MAX30102_ADDR, 0x05, 0x00);           // OVF_COUNTER  } starting, as
    ok &= i2cWriteReg(MAX30102_ADDR, 0x06, 0x00);           // FIFO_RD_PTR  } p.14 recommends
    ok &= i2cWriteReg(MAX30102_ADDR, 0x09, 0x03);           // MODE = SpO2
    ok &= i2cReadReg(MAX30102_ADDR, 0x08, rb, 6);           // 0x08..0x0D read back
    ppg.errRun = 0;
    ppg.present = ok && id == 0x15;                         // PART_ID (p.11)
    Serial.printf("# sens ppg: addr:57 part:%02X rev:%02X fifo:%02X mode:%02X spo2:%02X "
                  "pa:%02X/%02X sps:%d %s\n",
                  id, rev, rb[0], rb[1], rb[2], rb[4], rb[5], PPG_SPS,
                  ppg.present ? "ok" : (id != 0x15 ? "NOT USED: part id is not 15"
                                                   : "NOT USED: a write failed"));
    return ppg.present;
}

static void servicePpg()
{
    if (!ppg.present) return;
    uint8_t p[3];
    if (!i2cReadReg(MAX30102_ADDR, 0x04, p, 3)) { sensFail(ppg, "ppg"); return; }
    uint32_t us = micros();
    uint32_t idx = sampleIndex;
    uint8_t wr = p[0] & 0x1F, ovf = p[1] & 0x1F, rd = p[2] & 0x1F;
    uint8_t avail = (wr - rd) & 0x1F;                       // p.16
    // Full and empty both read wr == rd; a non-zero overflow count tells them
    // apart. The datasheet does not say what the pointers read when full, so
    // this is our reading of a 32-deep FIFO with 5-bit pointers.
    if (avail == 0 && ovf > 0) avail = 32;
    // Normally 1-2 samples wait here. After an overflow, empty the FIFO in one
    // go so the lost samples can be accounted at one known place in the stream.
    if (!ovf && avail > PPG_MAX_PER_READ) avail = PPG_MAX_PER_READ;

    while (avail) {
        uint8_t take = avail > PPG_MAX_PER_READ ? PPG_MAX_PER_READ : avail;
        uint8_t b[PPG_MAX_PER_READ * 6];
        // Reading FIFO_DATA does not advance the register address (p.14): one
        // burst returns consecutive samples, red then IR, 3 bytes each (p.15).
        if (!i2cReadReg(MAX30102_ADDR, 0x07, b, (size_t)take * 6)) { sensFail(ppg, "ppg"); return; }
        for (uint8_t i = 0; i < take; i++) {
            const uint8_t *q = &b[i * 6];
            uint32_t red = (((uint32_t)q[0] << 16) | ((uint32_t)q[1] << 8) | q[2]) & 0x3FFFF;
            uint32_t ir  = (((uint32_t)q[3] << 16) | ((uint32_t)q[4] << 8) | q[5]) & 0x3FFFF;
            ppg.n++;
            char line[64];
            int n = snprintf(line, sizeof(line), "P,%lu,%lu,%lu,%lu,%lu\n",
                             (unsigned long)ppg.n, (unsigned long)idx, (unsigned long)us,
                             (unsigned long)red, (unsigned long)ir);
            logSensorLine(line, n);
        }
        avail -= take;
    }
    if (ovf) {
        // The samples lost are the ones that arrived after the FIFO filled, so
        // they belong after everything just read. 0x1F is a saturated count.
        ppgFifoLost += ovf;
        ppg.n += ovf;
        Serial.printf("# sens ppg: FIFO overflow, %u%s samples lost before ppg_index %lu\n",
                      ovf, ovf == 0x1F ? " or more" : "", (unsigned long)(ppg.n + 1));
    }
    ppg.errRun = 0;
}

// MPU6050, register map RM-MPU-6000A-00 Rev 4.0. It powers up asleep
// (PWR_MGMT_1 = 0x40, p.8). +-2 g and +-250 deg/s as in the bring-up sketch
// (MAX30102_MPU6050_MAX30205.ino); DLPF 3 = 44 Hz accel / 42 Hz gyro (p.13);
// the output registers refresh at 1 kHz / (1 + 4) = 200 Hz (p.12) and we read
// the newest value on the ECG clock, so a reading is at most 5 ms old plus the
// filter's 4.9 ms delay. A 14-byte burst is one sampling instant (p.30). Its
// INT pin is not routed to the ESP32.
static bool initImu()
{
    static const uint8_t cand[2] = {MPU6050_ADDR_LO, MPU6050_ADDR_HI};
    uint8_t who = 0, rb[4] = {0}, pwr = 0;
    bool found = false;
    imu.present = false;
    for (uint8_t i = 0; i < 2 && !found; i++) {
        if (i2cReadReg(cand[i], 0x75, &who, 1)) { imu.addr = cand[i]; found = true; }
    }
    if (!found) {
        Serial.println("# sens imu: no answer at 0x68 or 0x69 (MPU6050 absent, or GYRO1 jumper open)");
        return false;
    }
    imuWhoAmI = who;
    bool ok = true;
    ok &= i2cWriteReg(imu.addr, 0x6B, 0x01);                // wake; clock = PLL, X gyro (p.41)
    ok &= i2cWriteReg(imu.addr, 0x19, 0x04);                // SMPLRT_DIV
    ok &= i2cWriteReg(imu.addr, 0x1A, 0x03);                // CONFIG: DLPF_CFG 3
    ok &= i2cWriteReg(imu.addr, 0x1B, 0x00);                // GYRO_CONFIG: +-250 deg/s
    ok &= i2cWriteReg(imu.addr, 0x1C, 0x00);                // ACCEL_CONFIG: +-2 g
    // On this board AD0 is not tied to a rail: it reaches only the AD1 header,
    // whose other pin is INT. With that jumper fitted the address follows the
    // INT pin, so INT must sit still: push-pull, active high, and no interrupt
    // enabled (pp.27-28) keeps it low and the address at 0x68.
    ok &= i2cWriteReg(imu.addr, 0x37, 0x00);                // INT_PIN_CFG
    ok &= i2cWriteReg(imu.addr, 0x38, 0x00);                // INT_ENABLE
    ok &= i2cReadReg(imu.addr, 0x19, rb, 4);
    ok &= i2cReadReg(imu.addr, 0x6B, &pwr, 1);
    imu.errRun = 0;
    imu.present = ok;
    // WHO_AM_I is 0x68 on a real MPU-6050 whatever AD0 is (p.46). Compatible
    // parts answer differently; we keep reading them but the log says so.
    Serial.printf("# sens imu: addr:%02X whoami:%02X smplrt:%02X cfg:%02X gyro:%02X accel:%02X "
                  "pwr:%02X every:%d %s%s\n",
                  imu.addr, who, rb[0], rb[1], rb[2], rb[3], pwr, IMU_EVERY,
                  ok ? "ok" : "NOT USED: a write failed",
                  who != 0x68 ? " (whoami is not 68: not an MPU-6050, scale unverified)" : "");
    return imu.present;
}

static void readImu()
{
    if (!imu.present) return;
    uint8_t b[14];
    uint32_t us = micros();
    uint32_t idx = sampleIndex;
    if (!i2cReadReg(imu.addr, 0x3B, b, 14)) { sensFail(imu, "imu"); return; }
    imu.errRun = 0;
    imu.n++;
    int16_t ax = (int16_t)((b[0]  << 8) | b[1]),  ay = (int16_t)((b[2]  << 8) | b[3]);
    int16_t az = (int16_t)((b[4]  << 8) | b[5]);            // b[6..7] is the die temperature
    int16_t gx = (int16_t)((b[8]  << 8) | b[9]),  gy = (int16_t)((b[10] << 8) | b[11]);
    int16_t gz = (int16_t)((b[12] << 8) | b[13]);
    char line[96];
    int n = snprintf(line, sizeof(line), "M,%lu,%lu,%lu,%d,%d,%d,%d,%d,%d\n",
                     (unsigned long)imu.n, (unsigned long)idx, (unsigned long)us,
                     ax, ay, az, gx, gy, gz);
    logSensorLine(line, n);
}

// MAX30205, datasheet 19-8505 Rev 0. Continuous conversion (configuration
// 0x00, the power-on state, p.10), one conversion per 44-50 ms (p.2); we read
// the latest once a second. 16-bit two's complement, MSB first, 0.00390625
// degC per LSB (p.11). The accuracy figures assume a sample period above 10 s
// to avoid self-heating (p.4 note 5), which continuous conversion does not
// meet: treat the absolute value as uncalibrated and use the trend.
static bool initTemp()
{
    uint8_t cfg = 0xFF, t[2] = {0};
    temp.present = false;
    if (!i2cWriteReg(MAX30205_ADDR, 0x01, 0x00) || !i2cReadReg(MAX30205_ADDR, 0x01, &cfg, 1)) {
        Serial.println("# sens temp: no answer at 0x48 (MAX30205 absent, or TEMP1 jumper open)");
        return false;
    }
    bool ok = i2cReadReg(MAX30205_ADDR, 0x00, t, 2);
    temp.errRun = 0;
    temp.present = ok;
    Serial.printf("# sens temp: addr:48 cfg:%02X raw:%d every:%d %s\n",
                  cfg, (int16_t)((t[0] << 8) | t[1]), TEMP_EVERY, ok ? "ok" : "NOT USED: read failed");
    return temp.present;
}

static void readTemp()
{
    if (!temp.present) return;
    uint8_t t[2];
    uint32_t us = micros();
    uint32_t idx = sampleIndex;
    if (!i2cReadReg(MAX30205_ADDR, 0x00, t, 2)) { sensFail(temp, "temp"); return; }
    temp.errRun = 0;
    temp.n++;
    char line[56];
    int n = snprintf(line, sizeof(line), "T,%lu,%lu,%lu,%d\n",
                     (unsigned long)temp.n, (unsigned long)idx, (unsigned long)us,
                     (int16_t)((t[0] << 8) | t[1]));
    logSensorLine(line, n);
}

// GSR: the op-amp output GSRSENSE behind 1 MOhm + 100 nF (a 1.6 Hz low-pass),
// read on the ESP32's own ADC at 11 dB. adc_sum is GSR_OVERSAMPLE raw 12-bit
// reads added up; mv_sum is the same number of reads through the core's
// calibration (analogReadMilliVolts), also added up. Neither is a conductance:
// the transfer function is in docs/sensor_inventory.md and is not yet measured.
static void readGsr()
{
    if (!gsrOn) return;
    uint32_t us = micros();
    uint32_t idx = sampleIndex;
    uint32_t raw = 0, mv = 0;
    for (int i = 0; i < GSR_OVERSAMPLE; i++) {
        raw += analogRead((uint8_t)GSR_ADC_PIN);
        mv  += analogReadMilliVolts((uint8_t)GSR_ADC_PIN);
    }
    gsrN++;
    char line[64];
    int n = snprintf(line, sizeof(line), "G,%lu,%lu,%lu,%lu,%lu\n",
                     (unsigned long)gsrN, (unsigned long)idx, (unsigned long)us,
                     (unsigned long)raw, (unsigned long)mv);
    logSensorLine(line, n);
}

// Probe and configure everything that is wired. Safe to call again while
// running ('i'): it takes about 25 ms, well inside the ECG FIFO's 125 ms.
// Sequence numbers are not restarted, so a capture stays monotonic across it.
void initSensors(const char *why)
{
    if (SENS_SDA_PIN < 0 && GSR_ADC_PIN < 0) {
        Serial.println("# sens: none wired on this board");
        return;
    }
    Serial.printf("# sens: probing%s, i2c sda=%d scl=%d %lu Hz, gsr adc pin=%d\n",
                  why, SENS_SDA_PIN, SENS_SCL_PIN, (unsigned long)sensI2cHz, GSR_ADC_PIN);
    if (SENS_SDA_PIN >= 0) {
        if (!sensBusUp) {
            Wire.begin(SENS_SDA_PIN, SENS_SCL_PIN, sensI2cHz);
            Wire.setTimeOut(SENS_I2C_TIMEOUT_MS);
            sensBusUp = true;
        }
        initImu();
        initPpg();
        initTemp();
    }
    if (GSR_ADC_PIN >= 0) {
        analogSetPinAttenuation((uint8_t)GSR_ADC_PIN, ADC_11db);
        gsrOn = true;
        Serial.printf("# sens gsr: adc pin:%d atten:11dB sum_of:%d every:%d ok\n",
                      GSR_ADC_PIN, GSR_OVERSAMPLE, GSR_EVERY);
    }
}

// Called on every pass of loop(), but does nothing until the ECG drain has
// produced new samples - so sensor work always follows ECG work and happens
// once per drain. The IMU goes first: its reading is the one tied most
// closely to the ECG sample it is stamped with.
void serviceSensors()
{
    static uint32_t lastIdx = 0, imuSlot = 0, gsrSlot = 0, tempSlot = 0;
    if (sampleIndex == lastIdx) return;
    lastIdx = sampleIndex;
    uint32_t s;
    if ((s = sampleIndex / IMU_EVERY)  != imuSlot)  { imuSlot = s;  readImu(); }
    servicePpg();
    if ((s = sampleIndex / GSR_EVERY)  != gsrSlot)  { gsrSlot = s;  readGsr(); }
    if ((s = sampleIndex / TEMP_EVERY) != tempSlot) { tempSlot = s; readTemp(); }
}

void logSensorStats()
{
    if (SENS_SDA_PIN < 0 && GSR_ADC_PIN < 0) return;
    Serial.printf("# sens: i2c:%luk ppg:%d n:%lu fifo_lost:%lu err:%lu pa:%02X part:%02X "
                  "| imu:%d@%02X n:%lu err:%lu whoami:%02X | temp:%d n:%lu err:%lu "
                  "| gsr:%d n:%lu | logdrop:%lu\n",
                  (unsigned long)(sensI2cHz / 1000),
                  ppg.present, (unsigned long)ppg.n, (unsigned long)ppgFifoLost,
                  (unsigned long)ppg.errs, ppgLedPa, ppgPartId,
                  imu.present, imu.addr, (unsigned long)imu.n, (unsigned long)imu.errs, imuWhoAmI,
                  temp.present, (unsigned long)temp.n, (unsigned long)temp.errs,
                  gsrOn, (unsigned long)gsrN, (unsigned long)sensLogDropped);
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
    // A transmit buffer larger than the default (the UART's 128-byte hardware
    // FIFO on the reference board, 256 bytes on the C3's USB-CDC). The sensor
    // lines make the output bursty, and logSample() drops a line rather than
    // wait, so the buffer has to absorb a burst. Must be set before begin().
    Serial.setTxBufferSize(SERIAL_TX_BUFFER);
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

    // Before the ECG interrupt is armed, so the probe's delays cost no samples.
    initSensors("");

    setupEcgInterrupt();
    max30003.writeRegister(REG_FIFO_RST, 0x000000);  // start from a clean FIFO
    lastStatsMs = millis();
    Serial.println("# fmt: S,index,isr_micros,value,etag,leadoff");
    Serial.println("# fmt: K,sync_count,sync_micros,sample_index");
    if (SENS_SDA_PIN >= 0 || GSR_ADC_PIN >= 0) {
        Serial.println("# fmt: P,ppg_index,ecg_index,micros,red,ir");
        Serial.println("# fmt: M,seq,ecg_index,micros,ax,ay,az,gx,gy,gz");
        Serial.println("# fmt: T,seq,ecg_index,micros,raw");
        Serial.println("# fmt: G,seq,ecg_index,micros,adc_sum,mv_sum");
    }
    Serial.printf("# device: %s  cs=%d int1=%d sync=%d ble=%d sps=%d\n",
                  DEVICE_TAG, MAX30003_CS_PIN, MAX30003_INT1_PIN,
                  SYNC_PIN, ENABLE_BLE, ECG_SPS);
    logInputConfig("");
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

// Input multiplexer / calibration-source configurations for the bench test in
// docs/bench_session_plan.md (datasheet check #21 and #23). Register fields
// (Rev 3 pp.35-36): CNFG_EMUX D23 POL, D21 OPENP, D20 OPENN, D[19:18] CALP_SEL,
// D[17:16] CALN_SEL; CNFG_CAL D22 EN_VCAL, D21 VMODE, D20 VMAG, D[14:12] FCAL,
// D11 FIFTY.
//   'd'  0x0B0000 / 0x720000  what the library's begin() leaves: electrodes
//        connected AND VCALP/VCALN switched onto both inputs (the open issue)
//   'e'  0x000000 / 0x000000  electrodes only, calibration disabled
//   'c'  0x390000 / 0x702800  scale test: electrodes disconnected inside the
//        chip, ECGP <- VCALP, ECGN <- VMID; bipolar 0.5 mV, ~16 Hz, 50% duty
// The active values are read back from the chip and logged on every change and
// every 5 s ("# cfg ..."), so every capture log records what it was taken in.
static const char *inputMode = "begin";

void logInputConfig(const char *why)
{
    uint8_t e[3] = {0}, c[3] = {0};
    max30003.readRegister(REG_CNFG_EMUX, e, 3);
    max30003.readRegister(REG_CNFG_CAL, c, 3);
    Serial.printf("# cfg emux:%02X%02X%02X cal:%02X%02X%02X mode:%s%s\n",
                  e[0], e[1], e[2], c[0], c[1], c[2], inputMode, why);
}

void setInputConfig(const char *mode, uint32_t emux, uint32_t cal)
{
    // CALP_SEL/CALN_SEL select VCALP/VCALN "only if CAL_EN_VCAL = 1" (p.36), so
    // enable the source before routing it, and unroute it before disabling it.
    bool routesCal = (emux & 0x0F0000UL) != 0;
    if (routesCal) {
        max30003.writeRegister(REG_CNFG_CAL, cal);
        max30003.writeRegister(REG_CNFG_EMUX, emux);
    } else {
        max30003.writeRegister(REG_CNFG_EMUX, emux);
        max30003.writeRegister(REG_CNFG_CAL, cal);
    }
    max30003.writeRegister(REG_FIFO_RST, 0x000000);
    inputMode = mode;
    logInputConfig(" (set)");
}

void loop()
{
    // 'b' toggles body bias, 'r' resets the FIFO; 'd' / 'e' / 'c' set the input
    // configuration (see setInputConfig). Extra sensors: 'i' probes them again,
    // 'p' steps the PPG LED current, 'f' switches the I2C clock.
    if (Serial.available()) {
        int c = Serial.read();
        if (c == 'b') { static bool rb = false; rb = !rb; setRbias(rb); }
        else if (c == 'r') { max30003.writeRegister(REG_FIFO_RST, 0x000000); }
        else if (c == 'd') { setInputConfig("d", 0x0B0000UL, 0x720000UL); }
        else if (c == 'e') { setInputConfig("e", 0x000000UL, 0x000000UL); }
        else if (c == 'c') { setInputConfig("c", 0x390000UL, 0x702800UL); }
        else if (c == 'i') { initSensors(" again ('i')"); }
        else if (c == 'p' && SENS_SDA_PIN >= 0) {
            // 2.0 / 6.2 / 12.6 / 25.4 mA typical (MAX30102 p.20: 0.2 mA per step).
            // Too little light is a flat trace; too much pins red/ir at 262143.
            static const uint8_t steps[] = {0x0A, 0x1F, 0x3F, 0x7F};
            static uint8_t at = 1;
            at = (at + 1) % sizeof(steps);
            ppgLedPa = steps[at];
            uint8_t rb[2] = {0};
            i2cWriteReg(MAX30102_ADDR, 0x0C, ppgLedPa);
            i2cWriteReg(MAX30102_ADDR, 0x0D, ppgLedPa);
            i2cReadReg(MAX30102_ADDR, 0x0C, rb, 2);
            Serial.printf("# sens ppg: pa:%02X/%02X (set) at ecg_index %lu\n",
                          rb[0], rb[1], (unsigned long)sampleIndex);
        }
        else if (c == 'f' && SENS_SDA_PIN >= 0) {
            sensI2cHz = (sensI2cHz == 400000) ? 100000 : 400000;
            Wire.setClock(sensI2cHz);
            Serial.printf("# sens: i2c clock %lu Hz (set)\n", (unsigned long)sensI2cHz);
        }
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

    // Extra sensors, only ever after the ECG FIFO has been seen to.
    serviceSensors();

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
        logInputConfig("");
        logSensorStats();
    }
}
