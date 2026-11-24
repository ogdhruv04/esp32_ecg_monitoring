// flex_bringup.ino - first power-up check for the HEALTH_FLEX_C3 ring board
// (schematic HEALTH_FLEX_C3_WITH_BMS, 30 Oct 2026).
//
// ESP32 Arduino core only, no libraries. Board: "ESP32C3 Dev Module",
// USB CDC On Boot: Disabled (Serial = UART0 = the RX1/TX1 pads), Flash Mode: DIO.
// Serial monitor: 115200 baud. Send 'r' to run every check again.
//
// What it checks, in order, and how each pin was read off the schematic
// (U3 = ESP32-C3, QFN32 pin numbers):
//   1. chip model, revision, flash (size and JEDEC ID), MAC
//   2. LED D2 blinks for 5 s. D2's anode goes through R9 (5.1k) to 3V3 and its
//      cathode to GPIO8 (U3 pin 14), so LOW = on. It is dim (well under 1 mA)
//      and, because GPIO8 is also SDA, it flickers whenever the I2C bus is busy.
//   3. I2C bus idle levels, then a scan on SDA = GPIO8 (pin 14), SCL = GPIO9
//      (pin 15). Expected parts:
//        0x57 MAX30102 (U7)  fixed address; PART_ID (0xFF) = 0x15
//        0x48 MAX30205 (U8)  A0 = A1 = A2 = GND
//        0x68/0x69 MPU6050 (U6)  AD0 (U6 pin 9) is not connected on the
//                            schematic, so either address is possible
//        0x36 MAX17055 (U10) fuel gauge; DevName (0x21) = 0x4010 on the
//                            initial silicon
//   4. the 1.8 V rail, measured with the ADC on GPIO3 (pin 8). GPIO3 carries
//      the MAX30102 interrupt (INT30102), which R17 (4.7k) pulls up to 1V8, so
//      once that interrupt is cleared the pin sits at the 1.8 V rail.
//   5. MAX30003 (U4) INFO register over SPI: SCK GPIO4 (pin 9, MTMS),
//      MISO GPIO5 (pin 10, MTDI), MOSI GPIO6 (pin 12, MTCK), CS GPIO7
//      (pin 13, MTDO).
//   6. MAX17055 cell voltage and state of charge, if the gauge answers.
//   7. one RESULT line per item and an OVERALL line.
//
// Datasheet sources for every constant are in flex_bringup/README.md.

#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <esp_chip_info.h>
#include <esp_flash.h>
#include <esp_mac.h>

// ---- pins (U3 pin number in brackets) --------------------------------------
static const int PIN_LED_SDA  = 8;   // [14] SDA, also LED D2 cathode, strapping pin
static const int PIN_SCL      = 9;   // [15] SCL, also BOOT strap (pad "GND4")
static const int PIN_PPG_INT  = 3;   // [8]  INT30102, pulled to 1V8 by R17
static const int PIN_SCK      = 4;   // [9]
static const int PIN_MISO     = 5;   // [10]
static const int PIN_MOSI     = 6;   // [12]
static const int PIN_CS       = 7;   // [13]
static const int PIN_ECG_INTB = 10;  // [16] MAX30003 INTB (not used here)

// ---- expected I2C addresses -------------------------------------------------
static const uint8_t ADDR_MAX30102 = 0x57;
static const uint8_t ADDR_MAX30205 = 0x48;
static const uint8_t ADDR_MPU_LO   = 0x68;
static const uint8_t ADDR_MPU_HI   = 0x69;
static const uint8_t ADDR_MAX17055 = 0x36;

// ---- results ----------------------------------------------------------------
enum Verdict : uint8_t { V_PASS, V_FAIL, V_LOOK, V_INFO };
struct Item { const char* name; Verdict v; char detail[112]; };
static Item items[12];
static int nItems = 0;

static void record(const char* name, Verdict v, const char* fmt, ...) {
    if (nItems >= (int)(sizeof(items) / sizeof(items[0]))) return;
    Item& it = items[nItems++];
    it.name = name; it.v = v;
    va_list ap; va_start(ap, fmt);
    vsnprintf(it.detail, sizeof(it.detail), fmt, ap);
    va_end(ap);
}

static const char* verdictText(Verdict v) {
    switch (v) {
        case V_PASS: return "PASS";
        case V_FAIL: return "FAIL";
        case V_LOOK: return "LOOK";
        default:     return "INFO";
    }
}

static void printResults() {
    int pass = 0, fail = 0;
    Serial.println();
    for (int i = 0; i < nItems; i++) {
        Serial.printf("RESULT %-9s %s  %s\n", items[i].name, verdictText(items[i].v), items[i].detail);
        if (items[i].v == V_PASS) pass++;
        if (items[i].v == V_FAIL) fail++;
    }
    Serial.printf("OVERALL %s  (%d pass, %d fail; LOOK items are checked by eye)\n",
                  fail == 0 ? "PASS" : "FAIL", pass, fail);
    Serial.println("# send 'r' to run all checks again");
}

// ---- I2C helpers ------------------------------------------------------------
static bool i2cPresent(uint8_t addr) {
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
}

static bool i2cRead(uint8_t addr, uint8_t reg, uint8_t* buf, size_t n) {
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom((int)addr, (int)n) != (int)n) return false;
    for (size_t i = 0; i < n; i++) buf[i] = Wire.read();
    return true;
}

// MAX17055 registers are 16-bit words sent LSB first (user guide p.37).
static bool max17055Word(uint8_t reg, uint16_t& out) {
    uint8_t b[2];
    if (!i2cRead(ADDR_MAX17055, reg, b, 2)) return false;
    out = (uint16_t)b[0] | ((uint16_t)b[1] << 8);
    return true;
}

static const char* nameFor(uint8_t a) {
    switch (a) {
        case ADDR_MAX30102: return "MAX30102 (PPG, U7)";
        case ADDR_MAX30205: return "MAX30205 (temperature, U8)";
        case ADDR_MPU_LO:   return "MPU6050 (IMU, U6), AD0 low";
        case ADDR_MPU_HI:   return "MPU6050 (IMU, U6), AD0 high";
        case ADDR_MAX17055: return "MAX17055 (fuel gauge, U10)";
        default:            return "UNEXPECTED: not on the schematic";
    }
}

// ---- MAX30003 ---------------------------------------------------------------
// Read header = (address << 1) | 1, then 24 data bits, SPI mode 0
// (MAX30003 datasheet Rev 3, p.14 and p.32).
static uint32_t max30003Read(uint8_t reg) {
    SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));
    digitalWrite(PIN_CS, LOW);
    SPI.transfer((uint8_t)((reg << 1) | 1));
    uint32_t v = 0;
    for (int i = 0; i < 3; i++) v = (v << 8) | SPI.transfer(0xFF);
    digitalWrite(PIN_CS, HIGH);
    SPI.endTransaction();
    return v;
}

// ---- the checks -------------------------------------------------------------
static void checkChip() {
    esp_chip_info_t ci;
    esp_chip_info(&ci);
    const char* model = ESP.getChipModel();
    bool isC3 = (ci.model == CHIP_ESP32C3);
    bool emb = (ci.features & CHIP_FEATURE_EMB_FLASH) != 0;
    uint8_t mac[6] = {0};
    esp_efuse_mac_get_default(mac);
    Serial.printf("# chip: %s, revision v%d.%d, %d core(s), embedded flash: %s\n",
                  model, ci.revision / 100, ci.revision % 100, ci.cores, emb ? "yes" : "no");
    Serial.printf("# MAC (base, eFuse): %02X:%02X:%02X:%02X:%02X:%02X\n",
                  mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    record("CHIP", isC3 ? V_PASS : V_FAIL, "%s rev v%d.%d, MAC %02X:%02X:%02X:%02X:%02X:%02X",
           model, ci.revision / 100, ci.revision % 100,
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

    uint32_t phys = 0, jedec = 0;
    esp_flash_get_physical_size(esp_flash_default_chip, &phys);
    esp_flash_read_id(esp_flash_default_chip, &jedec);
    uint32_t hdr = ESP.getFlashChipSize();
    Serial.printf("# flash: JEDEC ID 0x%06lX, detected %lu KB, image header says %lu KB, mode %d (2 = DIO)\n",
                  (unsigned long)jedec, (unsigned long)(phys / 1024), (unsigned long)(hdr / 1024),
                  (int)ESP.getFlashChipMode());
    bool flashOk = phys > 0 && jedec != 0 && jedec != 0xFFFFFF && phys >= hdr;
    record("FLASH", flashOk ? V_PASS : V_FAIL, "JEDEC 0x%06lX, %lu KB detected (image built for %lu KB)",
           (unsigned long)jedec, (unsigned long)(phys / 1024), (unsigned long)(hdr / 1024));
}

static void blinkLed() {
    Serial.println("# LED D2: blinking 5 s (2 Hz). It is dim: look closely, shade it from room light.");
    Wire.end();                                        // GPIO8 is SDA: release it on a re-run
    pinMode(PIN_LED_SDA, OUTPUT);
    uint32_t t0 = millis();
    bool on = false;
    while (millis() - t0 < 5000) {
        on = !on;
        digitalWrite(PIN_LED_SDA, on ? LOW : HIGH);   // LOW = on
        delay(250);
    }
    digitalWrite(PIN_LED_SDA, HIGH);
    pinMode(PIN_LED_SDA, INPUT);                       // hand the line back to the pull-ups
    record("LED", V_LOOK, "D2 should have blinked 10 times in 5 s");
}

static bool foundMax30102 = false, foundMax17055 = false;

static void checkI2c() {
    // Idle levels first, with the ESP32's own pull-ups off: only the board's
    // resistors hold the lines up. Both must read 1, or nothing on the bus can work.
    pinMode(PIN_LED_SDA, INPUT);
    pinMode(PIN_SCL, INPUT);
    delay(2);
    int sda = digitalRead(PIN_LED_SDA), scl = digitalRead(PIN_SCL);
    record("I2C_IDLE", (sda && scl) ? V_PASS : V_FAIL, "SDA=%d SCL=%d (both must be 1)", sda, scl);

    Wire.begin(PIN_LED_SDA, PIN_SCL, 100000);
    Wire.setTimeOut(50);
    Serial.println("# I2C scan, SDA GPIO8 / SCL GPIO9, 100 kHz:");
    int n = 0;
    bool mpu = false;
    uint8_t mpuAddr = 0;
    for (uint8_t a = 1; a < 0x7F; a++) {
        if (!i2cPresent(a)) continue;
        n++;
        Serial.printf("#   0x%02X  %s\n", a, nameFor(a));
        if (a == ADDR_MPU_LO || a == ADDR_MPU_HI) { mpu = true; mpuAddr = a; }
    }
    Serial.printf("# %d device(s) found\n", n);

    // MAX30102: PART_ID 0xFF reads 0x15 (datasheet 19-7740 Rev 1, p.11).
    uint8_t b[2];
    foundMax30102 = i2cPresent(ADDR_MAX30102);
    if (!foundMax30102) record("MAX30102", V_FAIL, "no answer at 0x57");
    else if (!i2cRead(ADDR_MAX30102, 0xFF, b, 1)) record("MAX30102", V_FAIL, "0x57 answers but PART_ID read failed");
    else record("MAX30102", b[0] == 0x15 ? V_PASS : V_FAIL, "0x57, PART_ID 0x%02X (expect 0x15)", b[0]);

    // MAX30205: no ID register. Configuration (0x01) powers up as 0x00 and the
    // temperature (0x00) is 16-bit MSB first, 1/256 degC per LSB (Rev 0, pp.10-12).
    if (!i2cPresent(ADDR_MAX30205)) {
        record("MAX30205", V_FAIL, "no answer at 0x48");
    } else {
        uint8_t cfg = 0xFF;
        bool okCfg = i2cRead(ADDR_MAX30205, 0x01, &cfg, 1);
        bool okT = i2cRead(ADDR_MAX30205, 0x00, b, 2);
        float t = (int16_t)((b[0] << 8) | b[1]) / 256.0f;
        bool plausible = okT && t > 5.0f && t < 60.0f;
        record("MAX30205", (okCfg && plausible) ? V_PASS : V_FAIL,
               "0x48, config 0x%02X, %.2f degC (uncalibrated; expect room/skin temperature)", cfg, t);
    }

    // MPU6050: WHO_AM_I (0x75) reads 0x68 whatever AD0 is (RM Rev 4.0, p.46).
    if (!mpu) {
        record("MPU6050", V_FAIL, "no answer at 0x68 or 0x69");
    } else if (!i2cRead(mpuAddr, 0x75, b, 1)) {
        record("MPU6050", V_FAIL, "0x%02X answers but WHO_AM_I read failed", mpuAddr);
    } else {
        record("MPU6050", b[0] == 0x68 ? V_PASS : V_FAIL,
               "0x%02X, WHO_AM_I 0x%02X (expect 0x68)", mpuAddr, b[0]);
    }

    foundMax17055 = i2cPresent(ADDR_MAX17055);
}

static void check1v8() {
    // The MAX30102 raises a power-ready interrupt at power-up and holds INT low
    // until Interrupt Status 1 (0x00) is read (datasheet p.12-13). Measure once
    // before clearing (for information) and once after (the rail).
    analogSetPinAttenuation(PIN_PPG_INT, ADC_11db);
    uint32_t before = analogReadMilliVolts(PIN_PPG_INT);
    if (foundMax30102) {
        uint8_t s[2];
        i2cRead(ADDR_MAX30102, 0x00, s, 2);   // reads 0x00 and 0x01, clears both
    }
    delay(5);
    uint32_t sum = 0;
    for (int i = 0; i < 16; i++) sum += analogReadMilliVolts(PIN_PPG_INT);
    uint32_t mv = sum / 16;
    Serial.printf("# GPIO3 / INT30102: %lu mV before clearing the MAX30102 interrupt, %lu mV after\n",
                  (unsigned long)before, (unsigned long)mv);
    bool ok = mv >= 1700 && mv <= 1900;
    record("1V8", ok ? V_PASS : V_FAIL,
           "%lu mV on GPIO3 via R17 (ADC estimate, accept 1700-1900; confirm with a meter)",
           (unsigned long)mv);
}

static void checkMax30003() {
    pinMode(PIN_CS, OUTPUT);
    digitalWrite(PIN_CS, HIGH);
    SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, -1);
    // INFO is not valid if it is the first command after power-up or SW_RST
    // (p.32), so read it once to throw away, then twice to compare.
    (void)max30003Read(0x0F);
    delay(2);
    uint32_t a = max30003Read(0x0F);
    uint32_t b = max30003Read(0x0F);
    uint8_t top  = (a >> 20) & 0xF;   // [23:20] fixed 0101
    uint8_t rev  = (a >> 16) & 0xF;   // [19:16] REV_ID
    uint8_t part = (a >> 12) & 0x3;   // [13:12] fixed 11 (Table 18)
    Serial.printf("# MAX30003 INFO (0x0F): 0x%06lX (repeat 0x%06lX); [23:20]=0x%X rev=%u [13:12]=%u, "
                  "serial bits [11:0]=0x%03lX\n",
                  (unsigned long)a, (unsigned long)b, top, rev, part, (unsigned long)(a & 0xFFF));
    if (a != b) {
        record("MAX30003", V_FAIL, "INFO unstable: 0x%06lX then 0x%06lX (SPI wiring or 1V8)",
               (unsigned long)a, (unsigned long)b);
    } else if (a == 0x000000 || a == 0xFFFFFF) {
        record("MAX30003", V_FAIL, "INFO 0x%06lX: no SPI answer (MISO stuck; check 1V8 and U4)",
               (unsigned long)a);
    } else if (top == 0x5 && part == 0x3) {
        if (rev == 1)
            record("MAX30003", V_PASS, "INFO 0x%06lX, REV_ID 1 as on the reference board (0x513261)",
                   (unsigned long)a);
        else
            record("MAX30003", V_PASS, "INFO 0x%06lX, REV_ID %u (reference board has 1: note it)",
                   (unsigned long)a, rev);
    } else {
        record("MAX30003", V_FAIL, "INFO 0x%06lX does not match 0x5?[bit13:12=11]??? (reference 0x513261)",
               (unsigned long)a);
    }
}

static void checkMax17055() {
    if (!foundMax17055) {
        record("MAX17055", V_FAIL, "no answer at 0x36");
        return;
    }
    // DevName 0x21 (UG p.33), VCell 0x09 at 78.125 uV/LSB (DS p.4, p.16),
    // RepSOC 0x06 at 1/256 % (DS p.16), Status 0x00 bit 1 = POR (UG p.25).
    uint16_t dev = 0, vcell = 0, soc = 0, status = 0;
    bool ok = max17055Word(0x21, dev) && max17055Word(0x09, vcell) &&
              max17055Word(0x06, soc) && max17055Word(0x00, status);
    if (!ok) {
        record("MAX17055", V_FAIL, "0x36 answers but register reads failed");
        return;
    }
    float v = vcell * 78.125e-6f;
    float pct = soc / 256.0f;
    Serial.printf("# MAX17055: DevName 0x%04X, VCell %.3f V, RepSOC %.1f %%, Status 0x%04X (POR %d)\n",
                  dev, v, pct, status, (status >> 1) & 1);
    bool plausible = v > 2.5f && v < 4.6f;
    record("MAX17055", plausible ? V_PASS : V_FAIL,
           "0x36, DevName 0x%04X, cell %.3f V, SOC %.0f %% (gauge not configured: SOC is indicative only)",
           dev, v, pct);
}

static void runAll() {
    nItems = 0;
    Serial.println();
    Serial.println("# ==== flex_bringup: HEALTH_FLEX_C3 power-up check ====");
    checkChip();
    blinkLed();
    checkI2c();
    check1v8();
    checkMax30003();
    checkMax17055();
    printResults();
}

void setup() {
    Serial.begin(115200);
    delay(300);
    pinMode(PIN_ECG_INTB, INPUT);
    runAll();
}

void loop() {
    // Print the results again every 10 s, for a serial monitor opened late.
    static uint32_t last = millis();
    if (Serial.available()) {
        int c = Serial.read();
        if (c == 'r' || c == 'R') { runAll(); last = millis(); }
    }
    if (millis() - last > 10000) {
        printResults();
        last = millis();
    }
    delay(10);
}
