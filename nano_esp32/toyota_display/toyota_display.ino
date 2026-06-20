/*
 * LA070WV1-TD01 auxiliary controller
 * Target: Arduino Nano ESP32 (ESP32-S3, Arduino core 3.x)
 *
 * The pixel-critical timing (SSPL, GSPU, GSC) is driven DIRECTLY from the Pi's
 * pixel-locked sync outputs — NOT regenerated here. A software ISR cannot place
 * an edge with 30 ns precision relative to the 33.26 MHz source clock, which is
 * what caused the horizontal jitter/scanning. See LA070WV1-TD01_pinout.md.
 *
 *   Pi GPIO2 (HSYNC) → FPC 59 (SSPL) + FPC 8 (GSC)   [direct, jitter-free]
 *   Pi GPIO3 (VSYNC) → FPC 6  (GSPU)                 [direct, jitter-free]
 *   Pi GPIO0 (PCLK)  → FPC 20 (SSC)
 *   Pi GPIO1 (DE)    → FPC 27 (SOE)
 *
 * This sketch keeps only the non-pixel-critical jobs (µs-tolerant):
 *   D2 ← HSYNC  (Pi GPIO 2, line-rate reference for POL)
 *   D6 → GOE    gate output enable     FPC pin 9  (active-low; held enabled)
 *   D7 → POL    polarity (per line)    FPC pin 26
 * plus touchscreen, backlight, and UART to the Pi.
 *
 * Inputs  (4-wire resistive touchscreen):
 *   A2  ↔ Touch A+  adapter pin 1  (~530Ω axis)
 *   A1  ↔ Touch B+  adapter pin 3  (~177Ω axis)
 *   D11 ↔ Touch A−  adapter pin 5
 *   D10 ↔ Touch B−  adapter pin 7
 *
 * UART to Pi (Pi GPIO 22/23, /dev/ttyAMA3, 115200 baud):
 *   D13 → Pi GPIO 23 (Pi RX)   — touch events: "T <x> <y>\n", release: "U\n"
 *   A0  ← Pi GPIO 22 (Pi TX)   — commands: 'e' enable, 'd' disable
 */

#define HSYNC_IN  D2   // Pi GPIO 2, line-rate reference for POL toggling
#define GOE_OUT   D6
#define POL_OUT   D7

// ── Touch ─────────────────────────────────────────────────────────────────────
#define TOUCH_AP  A2   // ADC1 (GPIO3)
#define TOUCH_BP  A1   // ADC1 (GPIO2)
#define TOUCH_AN  D11
#define TOUCH_BN  D10

#define TOUCH_SAMPLES     8    // ADC reads averaged per axis
#define TOUCH_SETTLE_US  100   // settling time after switching drive pins
#define TOUCH_INTERVAL_MS 20   // poll rate ~50 Hz

// Calibration — raw ADC values at each edge
#define CAL_Y_TOP     643
#define CAL_Y_BOTTOM  3419
#define CAL_X_LEFT    3961
#define CAL_X_RIGHT   245

// Display resolution
#define DISPLAY_W  800
#define DISPLAY_H  480

struct TouchPoint { int x; int y; };

static int adc_average(int pin) {
  long sum = 0;
  for (int i = 0; i < TOUCH_SAMPLES; i++) sum += analogRead(pin);
  return (int)(sum / TOUCH_SAMPLES);
}

// Drive A axis, read B+ with ADC — any value above noise floor means touched.
#define TOUCH_THRESHOLD 200  // out of 4095; raise if false positives, lower if misses

static bool touch_detect() {
  pinMode(TOUCH_AP, OUTPUT); digitalWrite(TOUCH_AP, HIGH);
  pinMode(TOUCH_AN, OUTPUT); digitalWrite(TOUCH_AN, LOW);
  pinMode(TOUCH_BP, INPUT_PULLDOWN);
  pinMode(TOUCH_BN, INPUT);
  delayMicroseconds(TOUCH_SETTLE_US);
  return adc_average(TOUCH_BP) > TOUCH_THRESHOLD;
}

static TouchPoint touch_read() {
  // X: drive B axis, read A+
  pinMode(TOUCH_BP, OUTPUT); digitalWrite(TOUCH_BP, HIGH);
  pinMode(TOUCH_BN, OUTPUT); digitalWrite(TOUCH_BN, LOW);
  pinMode(TOUCH_AP, INPUT);
  pinMode(TOUCH_AN, INPUT);
  delayMicroseconds(TOUCH_SETTLE_US);
  int raw_a = adc_average(TOUCH_AP);

  // Y: drive A axis, read B+
  pinMode(TOUCH_AP, OUTPUT); digitalWrite(TOUCH_AP, HIGH);
  pinMode(TOUCH_AN, OUTPUT); digitalWrite(TOUCH_AN, LOW);
  pinMode(TOUCH_BP, INPUT);
  pinMode(TOUCH_BN, INPUT);
  delayMicroseconds(TOUCH_SETTLE_US);
  int raw_b = adc_average(TOUCH_BP);

  // raw_a → screen Y (top=CAL_Y_TOP, bottom=CAL_Y_BOTTOM)
  // raw_b → screen X (left=CAL_X_LEFT, right=CAL_X_RIGHT)
  int x = constrain(map(raw_b, CAL_X_LEFT, CAL_X_RIGHT, 0, DISPLAY_W - 1), 0, DISPLAY_W - 1);
  int y = constrain(map(raw_a, CAL_Y_TOP,  CAL_Y_BOTTOM, 0, DISPLAY_H - 1), 0, DISPLAY_H - 1);

  return {x, y};
}

// ── Timing state ──────────────────────────────────────────────────────────────
static volatile bool pol_state = false;
static volatile bool enabled   = true;
static volatile uint32_t hsync_count = 0;

// HSYNC falling edge: flip polarity for AC drive. Not pixel-critical — POL only
// has to be stable across a line, and a few µs of ISR latency into a ~31 µs line
// is harmless. SSPL/GSC/GSPU are NOT generated here; the Pi drives them directly.
static void ARDUINO_ISR_ATTR hsync_isr() {
  hsync_count++;
  if (!enabled) return;
  pol_state = !pol_state;
  digitalWrite(POL_OUT, pol_state);
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200, SERIAL_8N1, A0, D13);  // RX=A0, TX=D13 (reserved, unused)

  pinMode(HSYNC_IN, INPUT);
  pinMode(GOE_OUT,  OUTPUT);
  pinMode(POL_OUT,  OUTPUT);

  // GOE active-low: hold gate output continuously enabled for the first bring-up.
  // If row-to-row ghosting appears, add a per-line GOE pulse later.
  digitalWrite(GOE_OUT,  LOW);
  digitalWrite(POL_OUT,  LOW);

  attachInterrupt(digitalPinToInterrupt(HSYNC_IN), hsync_isr, FALLING);
}

void loop() {
  // Handle Pi commands. 'e'/'d' now only gate POL and the gate output enable;
  // the Pi's own sync outputs drive SSPL/GSC/GSPU regardless.
  while (Serial1.available()) {
    char cmd = Serial1.read();
    if (cmd == 'e') {
      enabled = true;
      digitalWrite(GOE_OUT, LOW);   // enable gate output (active-low)
    } else if (cmd == 'd') {
      enabled = false;
      digitalWrite(GOE_OUT, HIGH);  // disable gate output
    }
  }

  // Poll touch at ~50 Hz
  static unsigned long last_touch_ms = 0;
  static unsigned long last_debug_ms = 0;
  static bool was_touched = false;

  unsigned long now = millis();
  if (now - last_debug_ms >= 1000) {
    last_debug_ms = now;
    // Sanity check: HSYNC should read ~31496. VSYNC is no longer wired here.
    Serial.printf("HSYNC/s=%u\n", hsync_count);
    hsync_count = 0;
  }

  if (now - last_touch_ms >= TOUCH_INTERVAL_MS) {
    last_touch_ms = now;

    if (touch_detect()) {
      was_touched = true;
    } else if (was_touched) {
      was_touched = false;
    }
  }
}
