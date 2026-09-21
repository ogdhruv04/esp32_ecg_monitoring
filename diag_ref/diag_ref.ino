// One-shot SPI diagnostic for the reference board.
// The old firmware talked to the MAX30003 fine and ours reads 0x000000, so
// something about OUR bus setup differs. Rather than guess, sweep it.
#include <SPI.h>

#define SCK_PIN  18
#define MISO_PIN 19
#define MOSI_PIN 23
#define REG_INFO 0x0F

// Candidate CS pins. Excludes 6-11 (flash), 15 (INTB input from the sensor),
// 21/22 (I2C), 34-39 (input-only), and the SPI trio itself.
const int CS_CANDIDATES[] = {4, 2, 5, 12, 13, 14, 16, 17, 25, 26, 27, 32, 33};

bool readInfo(int cs, uint8_t *b, uint32_t hz) {
  SPI.beginTransaction(SPISettings(hz, MSBFIRST, SPI_MODE0));
  digitalWrite(cs, LOW);
  SPI.transfer((REG_INFO << 1) | 0x01);
  for (int i = 0; i < 3; i++) b[i] = SPI.transfer(0xFF);
  digitalWrite(cs, HIGH);
  SPI.endTransaction();
  // MAX30003 INFO returns 0x5_ _ _ when the part is alive and clocked.
  return (b[0] & 0xF0) == 0x50;
}

void setup() {
  Serial.begin(115200);
  delay(2500);
  Serial.println("\n\n===== MAX30003 SPI DIAGNOSTIC =====");
  Serial.printf("bus pins: SCK=%d MISO=%d MOSI=%d\n", SCK_PIN, MISO_PIN, MOSI_PIN);

  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, -1);

  for (unsigned i = 0; i < sizeof(CS_CANDIDATES)/sizeof(int); i++)
    pinMode(CS_CANDIDATES[i], OUTPUT), digitalWrite(CS_CANDIDATES[i], HIGH);

  // Sweep CS pin x clock speed. A slow clock is included because the 3.3V/1.8V
  // level mismatch on this board degrades edges, and marginal levels fail at
  // high speed long before they fail at low speed.
  const uint32_t speeds[] = {2000000, 1000000, 250000, 100000};
  bool found = false;
  for (unsigned s = 0; s < 4; s++) {
    Serial.printf("\n--- SPI @ %lu Hz ---\n", (unsigned long)speeds[s]);
    for (unsigned i = 0; i < sizeof(CS_CANDIDATES)/sizeof(int); i++) {
      int cs = CS_CANDIDATES[i];
      uint8_t b[3] = {0};
      bool ok = readInfo(cs, b, speeds[s]);
      if (ok || b[0] || b[1] || b[2]) {
        Serial.printf("  CS=%-2d -> 0x%02X%02X%02X %s\n", cs, b[0], b[1], b[2],
                      ok ? "  <<<<< VALID MAX30003 ID" : "(non-zero)");
        if (ok) found = true;
      }
    }
    if (!found) Serial.println("  all candidates read 0x000000");
  }

  Serial.println("\n--- MISO line state (SPI released, pulled up) ---");
  SPI.end();
  pinMode(MISO_PIN, INPUT_PULLUP);
  delay(5);
  Serial.printf("  MISO with pullup: %d   (1 = line floats/idles high, 0 = held low)\n",
                digitalRead(MISO_PIN));
  pinMode(MISO_PIN, INPUT_PULLDOWN);
  delay(5);
  Serial.printf("  MISO with pulldown: %d  (1 = something is DRIVING it high)\n",
                digitalRead(MISO_PIN));
  Serial.println("\n===== END =====");
}

void loop() { delay(1000); }
