#!/usr/bin/env python3
# arduino-cli monitor doesn't reliably assert DTR on the ESP32-C3's native
# USB-CDC port, and its TinyUSB stack withholds Serial output until DTR is
# set. This asserts DTR explicitly, then streams lines until Ctrl+C.
import sys
import serial

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
baud = int(sys.argv[2]) if len(sys.argv) > 2 else 57600

ser = serial.Serial(port, baud, timeout=1)
ser.dtr = True
ser.rts = False

print(f"Monitoring {port} at {baud} baud. Press Ctrl+C to exit.")
try:
    while True:
        line = ser.readline()
        if line:
            sys.stdout.write(line.decode(errors="replace"))
            sys.stdout.flush()
except KeyboardInterrupt:
    pass
finally:
    ser.close()
