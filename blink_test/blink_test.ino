// Blink an LED on GPIO8 of the custom ESP32-C3 test board, 500 ms on/off.
// GPIO8 is a strapping pin (must be high to enter download mode), so an LED
// wired to it can affect flashing; it is safe to drive once the app runs.
// Serial goes to UART0 (the FTDI adapter) at 115200.
const int LED_PIN = 8;

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  Serial.println("# blink_test: GPIO8, 500 ms");
}

void loop() {
  static bool on = false;
  on = !on;
  digitalWrite(LED_PIN, on ? HIGH : LOW);
  Serial.printf("led %s\n", on ? "HIGH" : "LOW");
  delay(500);
}
