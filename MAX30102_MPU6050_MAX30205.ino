#include <Wire.h>
#include "Protocentral_MAX30205.h"
#include "MAX30105.h"
#include "heartRate.h"

MAX30205 tempSensor;
MAX30105 max30102;

// MPU6050 variables
long accelX, accelY, accelZ;
float gForceX, gForceY, gForceZ;
float lastGx = 0, lastGy = 0, lastGz = 0;

long gyroX, gyroY, gyroZ;
float rotX, rotY, rotZ;
float lastRotX = 0, lastRotY = 0, lastRotZ = 0;

// Sudden change thresholds
const float accelThreshold = 0.5;
const float gyroThreshold = 50.0;

// MAX30102 heart rate/spo2 variables
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute;
int beatAvg;

void setup() {
Serial.begin(115200);
delay(1000);
Serial.println("Started");

Wire.begin(8,9);  // Shared I2C

  // --- MAX30205 Setup ---
  while (!tempSensor.scanAvailableSensors()) {
    Serial.println("MAX30205 not found. Check wiring.");
    delay(3000);
  }
  tempSensor.begin();
  Serial.println("MAX30205 ready");

  // --- MPU6050 Setup ---
  setupMPU();
  Serial.println("MPU6050 ready");

  // --- MAX30102 Setup ---
  if (!max30102.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("MAX30102 not found. Check connections.");
    while (1);
  }
  max30102.setup();
  max30102.setPulseAmplitudeRed(0x0A);
  max30102.setPulseAmplitudeIR(0x0A);
  max30102.setPulseAmplitudeGreen(0);  // Not used
  Serial.println("MAX30102 ready");
}

void loop() {
  // --- MAX30205 Temperature ---
  float temp = tempSensor.getTemperature();
  Serial.print("Temp (°C): ");
  Serial.println(temp, 2);

 // --- MPU6050 Motion Detection ---
recordAccelRegisters();
recordGyroRegisters();

// Calculate total change in acceleration and rotation
float accelChange = abs(gForceX - lastGx) + abs(gForceY - lastGy) + abs(gForceZ - lastGz);
float gyroChange = abs(rotX - lastRotX) + abs(rotY - lastRotY) + abs(rotZ - lastRotZ);

// Apply thresholds
if (accelChange > 1.0) {
  Serial.println("⚠️ Sudden acceleration detected!");
}

if (gyroChange > 150.0) {
  Serial.println("⚠️ Sudden rotation detected!");
}

// Update previous values
lastGx = gForceX;
lastGy = gForceY;
lastGz = gForceZ;

lastRotX = rotX;
lastRotY = rotY;
lastRotZ = rotZ;


  if (abs(rotX - lastRotX) > gyroThreshold ||
      abs(rotY - lastRotY) > gyroThreshold ||
      abs(rotZ - lastRotZ) > gyroThreshold) {
    Serial.println("⚠️ Sudden rotation detected!");
  }

  lastGx = gForceX;
  lastGy = gForceY;
  lastGz = gForceZ;
  lastRotX = rotX;
  lastRotY = rotY;
  lastRotZ = rotZ;

  // --- MAX30102 Heart Rate and SpO2 ---
  long irValue = max30102.getIR();
  long redValue = max30102.getRed();

  if (checkForBeat(irValue)) {
    long delta = millis() - lastBeat;
    lastBeat = millis();
    beatsPerMinute = 60 / (delta / 1000.0);
    if (beatsPerMinute > 20 && beatsPerMinute < 255) {
      rates[rateSpot++] = (byte)beatsPerMinute;
      rateSpot %= RATE_SIZE;
      beatAvg = 0;
      for (byte i = 0; i < RATE_SIZE; i++) beatAvg += rates[i];
      beatAvg /= RATE_SIZE;
    }
  }

  float ratio = (float)redValue / (float)irValue;
  float spo2 = 110.0 - 25.0 * ratio;
  spo2 = constrain(spo2, 0.0, 100.0);

  // --- Print All Data ---
  Serial.print("Accel(g) X:");
  Serial.print(gForceX); Serial.print(" Y:"); Serial.print(gForceY); Serial.print(" Z:"); Serial.print(gForceZ);
  Serial.print(" | Gyro(deg/s) X:");
  Serial.print(rotX); Serial.print(" Y:"); Serial.print(rotY); Serial.print(" Z:"); Serial.print(rotZ);
  Serial.print(" | IR: "); Serial.print(irValue);
  Serial.print(" RED: "); Serial.print(redValue);
  Serial.print(" BPM: "); Serial.print(beatsPerMinute);
  Serial.print(" Avg BPM: "); Serial.print(beatAvg);
  Serial.print(" SpO2: "); Serial.print(spo2);
  Serial.println(" %");

  delay(1000);
}

// -------- MPU6050 Functions --------
void setupMPU() {
  Wire.beginTransmission(0x68);
  Wire.write(0x6B); Wire.write(0x00); Wire.endTransmission(); // Wake
  Wire.beginTransmission(0x68);
  Wire.write(0x1B); Wire.write(0x00); Wire.endTransmission(); // Gyro config
  Wire.beginTransmission(0x68);
  Wire.write(0x1C); Wire.write(0x00); Wire.endTransmission(); // Accel config
}

void recordAccelRegisters() {
  Wire.beginTransmission(0x68);
  Wire.write(0x3B);
  Wire.endTransmission();
  Wire.requestFrom(0x68, 6);
  while (Wire.available() < 6);
  accelX = Wire.read() << 8 | Wire.read();
  accelY = Wire.read() << 8 | Wire.read();
  accelZ = Wire.read() << 8 | Wire.read();
  gForceX = accelX / 16384.0;
  gForceY = accelY / 16384.0;
  gForceZ = accelZ / 16384.0;
}

void recordGyroRegisters() {
  Wire.beginTransmission(0x68);
  Wire.write(0x43);
  Wire.endTransmission();
  Wire.requestFrom(0x68, 6);
  while (Wire.available() < 6);
  gyroX = Wire.read() << 8 | Wire.read();
  gyroY = Wire.read() << 8 | Wire.read();
  gyroZ = Wire.read() << 8 | Wire.read();
  rotX = gyroX / 131.0;
  rotY = gyroY / 131.0;
  rotZ = gyroZ / 131.0;
}
