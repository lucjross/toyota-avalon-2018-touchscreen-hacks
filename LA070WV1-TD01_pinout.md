# LA070WV1-TD01 60-Pin FPC Pinout

Pi DPI mapping assumes `dtoverlay=dpi18`, 18-bit RGB666.
U/D tied LOW → scan top-to-bottom, GSPU active, GSPD unused.
L/R tied HIGH → scan left-to-right, SSPL active, SSPR unused.

| Pin | Symbol | Description | Connect to |
|-----|--------|-------------|------------|
| 1 | VCOM | Color filter substrate voltage (4.0V typ) | TCON board |
| 2 | VCOM | Color filter substrate voltage (4.0V typ) | TCON board |
| 3 | GND | Ground | GND |
| 4 | VGL | Gate driver negative voltage (-9.5V typ) | TCON board |
| 5 | VGL | Gate driver negative voltage (-9.5V typ) | TCON board |
| 6 | GSPU | Gate scan up start pulse | Nano ESP32 D4 |
| 7 | U/D | Vertical scan direction (LOW = top-to-bottom) | GND (static LOW) |
| 8 | GSC | Gate shift clock (~31.5 kHz) | Nano ESP32 D8 (PWM/timer) |
| 9 | GOE | Gate output enable | Nano ESP32 D6 |
| 10 | GSPD | Gate scan down start pulse (unused when U/D=LOW) | GND |
| 11 | VST | Voltage for storage capacitor (0V) | GND |
| 12 | GND | Ground | GND |
| 13 | VGH | Gate driver positive voltage (+18.5V typ) | TCON board |
| 14 | GND | Ground | GND |
| 15 | SSPR | Source scan right start pulse (unused when L/R=HIGH) | NC |
| 16 | DVDD | Logic supply 3.3V | Pi 3.3V |
| 17 | DVDD | Logic supply 3.3V | Pi 3.3V |
| 18 | DVDD | Logic supply 3.3V | Pi 3.3V |
| 19 | GND | Ground | GND |
| 20 | SSC | Source shift clock / pixel clock (33.26 MHz) | Pi GPIO 0 (PCLK) |
| 21 | GND | Ground | GND |
| 22 | GND | Ground | GND |
| 23 | GND | Ground | GND |
| 24 | AVDD | Source driver IC supply (10V typ) | TCON board |
| 25 | AVDD | Source driver IC supply (10V typ) | TCON board |
| 26 | POL | Polarity control (toggles each line) | Nano ESP32 D7 |
| 27 | SOE | Source output enable (≈ DE) | Pi GPIO 1 (DE) |
| 28 | L/R | Horizontal scan direction (HIGH = left-to-right) | DVDD / 3.3V (static HIGH) |
| 29 | REV | Pixel data inversion (LOW = normal) | GND (static LOW) |
| 30 | R5 | Red data 5 [MSB] | Pi GPIO 9 |
| 31 | R4 | Red data 4 | Pi GPIO 8 |
| 32 | R3 | Red data 3 | Pi GPIO 7 |
| 33 | R2 | Red data 2 | Pi GPIO 6 |
| 34 | R1 | Red data 1 | Pi GPIO 5 |
| 35 | R0 | Red data 0 [LSB] | Pi GPIO 4 |
| 36 | G5 | Green data 5 [MSB] | Pi GPIO 15 |
| 37 | G4 | Green data 4 | Pi GPIO 14 |
| 38 | G3 | Green data 3 | Pi GPIO 13 |
| 39 | G2 | Green data 2 | Pi GPIO 12 |
| 40 | G1 | Green data 1 | Pi GPIO 11 |
| 41 | G0 | Green data 0 [LSB] | Pi GPIO 10 |
| 42 | B5 | Blue data 5 [MSB] | Pi GPIO 21 |
| 43 | B4 | Blue data 4 | Pi GPIO 20 |
| 44 | B3 | Blue data 3 | Pi GPIO 19 |
| 45 | B2 | Blue data 2 | Pi GPIO 18 |
| 46 | B1 | Blue data 1 | Pi GPIO 17 |
| 47 | B0 | Blue data 0 [LSB] | Pi GPIO 16 |
| 48 | VREF10 | Gamma correction voltage (0.7V) | Resistor ladder |
| 49 | VREF9 | Gamma correction voltage (1.0V) | Resistor ladder |
| 50 | VREF8 | Gamma correction voltage (2.78V) | Resistor ladder |
| 51 | VREF7 | Gamma correction voltage (3.82V) | Resistor ladder |
| 52 | VREF6 | Gamma correction voltage (4.77V) | Resistor ladder |
| 53 | VREF5 | Gamma correction voltage (5.42V) | Resistor ladder |
| 54 | VREF4 | Gamma correction voltage (6.24V) | Resistor ladder |
| 55 | VREF3 | Gamma correction voltage (7.13V) | Resistor ladder |
| 56 | VREF2 | Gamma correction voltage (8.8V) | Resistor ladder |
| 57 | VREF1 | Gamma correction voltage (9.1V) | Resistor ladder |
| 58 | GND | Ground | GND |
| 59 | SSPL | Source scan left start pulse | Nano ESP32 D5 |
| 60 | GND | Ground | GND |

## Nano ESP32 Pin Summary

| Nano Pin | Signal | Direction |
|----------|--------|-----------|
| D2 | VSYNC from Pi GPIO 3 | Input (interrupt) |
| D3 | HSYNC from Pi GPIO 2 | Input (interrupt) |
| D4 | GSPU → FPC pin 6 | Output |
| D5 | SSPL → FPC pin 59 | Output |
| D6 | GOE → FPC pin 9 | Output |
| D7 | POL → FPC pin 26 | Output |
| D8 | GSC → FPC pin 8 | Output (PWM ~31.5 kHz) |
| A2 | Touch A+ → touchscreen adapter pin 1 (~530Ω axis) | ADC in / GPIO out |
| D10 | Touch B− → touchscreen adapter pin 7 | GPIO out only |
| D11 | Touch A− → touchscreen adapter pin 5 | GPIO out only |
| A1 | Touch B+ → touchscreen adapter pin 3 (~177Ω axis) | ADC in / GPIO out |
| D13 | (free) | — |
| A0 | (free) | — |

## Pi GPIO Summary

| BCM GPIO | Physical Pin | DPI Function | FPC Pin |
|----------|-------------|-------------|---------|
| 0 | 27 | PCLK | 20 (SSC) |
| 1 | 28 | DE | 27 (SOE) |
| 2 | 3 | HSYNC | → Nano D3 |
| 3 | 5 | VSYNC | → Nano D2 |
| 4 | 7 | R0 | 35 |
| 5 | 29 | R1 | 34 |
| 6 | 31 | R2 | 33 |
| 7 | 26 | R3 | 32 |
| 8 | 24 | R4 | 31 |
| 9 | 21 | R5 | 30 |
| 10 | 19 | G0 | 41 |
| 11 | 23 | G1 | 40 |
| 12 | 32 | G2 | 39 |
| 13 | 33 | G3 | 38 |
| 14 | 8 | G4 | 37 |
| 15 | 22 | G5 | 36 |
| 16 | 36 | B0 | 47 |
| 17 | 11 | B1 | 46 |
| 18 | 12 | B2 | 45 |
| 19 | 35 | B3 | 44 |
| 20 | 38 | B4 | 43 |
| 21 | 40 | B5 | 42 |
| 26 | 37 | Backlight enable → YS-DZ-3.1 Blue | — |

## VREF Gamma Resistor Ladder

Connects from AVDD (10V) to GND through the VREF pins in order.
Tap points provide the 10 gamma reference voltages for the source driver IC.
Use resistors from your kit — values below are nearest standard to ideal.

```
AVDD (10V)
    │
   910Ω
    │
   VREF1 (pin 57) — 9.1V
    │
   300Ω
    │
   VREF2 (pin 56) — 8.8V
    │
   1kΩ + 680Ω (series)
    │
   VREF3 (pin 55) — 7.13V
    │
   910Ω
    │
   VREF4 (pin 54) — 6.24V
    │
   820Ω
    │
   VREF5 (pin 53) — 5.42V
    │
   680Ω
    │
   VREF6 (pin 52) — 4.77V
    │
   1kΩ
    │
   VREF7 (pin 51) — 3.82V
    │
   1kΩ
    │
   VREF8 (pin 50) — 2.78V
    │
   1.8kΩ
    │
   VREF9 (pin 49) — 1.00V
    │
   300Ω
    │
   VREF10 (pin 48) — 0.70V
    │
   680Ω
    │
  GND
```

| Resistor | From | To | Voltage at tap |
|----------|------|----|----------------|
| 910Ω | AVDD (10V) | VREF1 (pin 57) | 9.1V |
| 300Ω | VREF1 | VREF2 (pin 56) | 8.8V |
| 1kΩ + 680Ω | VREF2 | VREF3 (pin 55) | 7.13V |
| 910Ω | VREF3 | VREF4 (pin 54) | 6.24V |
| 820Ω | VREF4 | VREF5 (pin 53) | 5.42V |
| 680Ω | VREF5 | VREF6 (pin 52) | 4.77V |
| 1kΩ | VREF6 | VREF7 (pin 51) | 3.82V |
| 1kΩ | VREF7 | VREF8 (pin 50) | 2.78V |
| 1.8kΩ | VREF8 | VREF9 (pin 49) | 1.00V |
| 300Ω | VREF9 | VREF10 (pin 48) | 0.70V |
| 680Ω | VREF10 | GND | — |

Total ladder resistance: ~9.07kΩ. Current draw from AVDD: ~1.1mA.

## YS-DZ-3.1 Backlight Boost Converter Wiring

### Input (6-pin harness)

| Harness Pin | Wire | Connect to |
|-------------|------|------------|
| 1 | Red | 12V |
| 2 | Red | 12V |
| 3 | Yellow | 12V |
| 4 | Blue | Pi GPIO 26 (physical pin 37) — backlight enable |
| 5 | — | NC |
| 6 | Black | GND |

### Output

| Wire | Connect to |
|------|------------|
| Red (positive) | CN1 adapter pin 1 (Anode) |
| Black (negative) | CN1 adapter pin 5 (Cathode) |

### Backlight LED FPC (CN1, 8-pin)

Adapter is numbered 8-to-1 (reversed from datasheet). Original Toyota wiring used pins 8 and 4.

| Datasheet Pin | Toyota Pin | Adapter Pin | Symbol | Connect to |
|---------------|------------|-------------|--------|------------|
| 1 | 8 | 1 | Anode | YS-DZ-3.1 output + (Red) |
| 2 | 7 | 2 | NC | — |
| 3 | 6 | 3 | NC | — |
| 4 | 5 | 4 | NC | — |
| 5 | 4 | 5 | Cathode | YS-DZ-3.1 output − (Black) |
| 6 | 3 | 6 | NC | — |
| 7 | 2 | 7 | NC | — |
| 8 | 1 | 8 | NC | — |

## Touchscreen (4-wire Resistive Overlay)

8-pin DIP adapter, pins doubled up: adapter pins 1&2 = same wire, 3&4, 5&6, 7&8.
X/Y axis assignment TBD — determine empirically during calibration.

| Adapter Pin | Signal | Nano ESP32 Pin | Note |
|-------------|--------|----------------|------|
| 1 | Axis A+ (~530Ω axis) | A2 | ADC1 (GPIO3) |
| 3 | Axis B+ (~177Ω axis) | A1 | ADC1 (GPIO2) |
| 5 | Axis A− | D11 | drive only |
| 7 | Axis B− | D10 | drive only |

VCC → 3.3V, GND → GND (shared with ESP32).

## Pi ↔ ESP32 Communication

Connected via USB (Pi USB-A → ESP32 USB). Appears as `/dev/ttyACM0` on the Pi.
ESP32 sends touch coordinates; Pi sends display enable/disable commands.
Baud rate: 115200.
