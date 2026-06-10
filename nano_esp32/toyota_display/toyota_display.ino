/*
 * LA070WV1-TD01 gate/source timing generator
 * Target: Arduino Nano ESP32 (ESP32-S3, Arduino core 3.x)
 *
 * Inputs  (from Pi DPI):
 *   D2 ← VSYNC  (Pi GPIO 3, active-low, ~60 Hz)
 *   D3 ← HSYNC  (Pi GPIO 2, active-low, ~31.5 kHz)
 *
 * Outputs (to FPC breakout):
 *   D4 → GSPU   gate start pulse up        FPC pin 6
 *   D5 → SSPL   source start pulse left    FPC pin 59
 *   D6 → GOE    gate output enable         FPC pin 9  (active-low)
 *   D7 → POL    polarity (toggle per line) FPC pin 26
 *   D8 → GSC    gate shift clock ~31.5kHz  FPC pin 8  (50% PWM)
 *
 * Inputs  (4-wire resistive touchscreen):
 *   D9  ↔ Touch A+  adapter pin 1  (~530Ω axis)
 *   D10 ↔ Touch B+  adapter pin 3  (~177Ω axis)
 *   D11 ↔ Touch A−  adapter pin 5
 *   D12 ↔ Touch B−  adapter pin 7
 *
 * UART to Pi (Pi GPIO 22/23, /dev/ttyAMA3, 115200 baud):
 *   D13 → Pi GPIO 23 (Pi RX)   — touch events: "T <x> <y>\n", release: "U\n"
 *   A0  ← Pi GPIO 22 (Pi TX)   — commands: 'e' enable, 'd' disable
 */

#include "esp_timer.h"

#define VSYNC_IN  D2
#define HSYNC_IN  D3
#define GSPU_OUT  D4
#define SSPL_OUT  D5
#define GOE_OUT   D6
#define POL_OUT   D7
#define GSC_OUT   D8

// GSC frequency = pixel_clock / h_total = 33,260,000 / 1056
#define GSC_HZ  31496

// Pulse widths in microseconds — widen if driver shows setup/hold violations
#define GSPU_US  32   // one GSC period
#define SSPL_US   2
#define GOE_US   15   // ~half line period; holds gate row active while source loads

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

// One-shot timer callbacks — run from ISR context (IRAM), no heap alloc
static void IRAM_ATTR gspu_end(void*) { digitalWrite(GSPU_OUT, LOW); }
static void IRAM_ATTR sspl_end(void*) { digitalWrite(SSPL_OUT, LOW); }
static void IRAM_ATTR goe_end(void*)  { digitalWrite(GOE_OUT,  HIGH); }

static esp_timer_handle_t gspu_timer;
static esp_timer_handle_t sspl_timer;
static esp_timer_handle_t goe_timer;

static void create_isr_timer(esp_timer_cb_t cb, esp_timer_handle_t* handle) {
  esp_timer_create_args_t args = {};
  args.callback        = cb;
  args.dispatch_method = ESP_TIMER_TASK;
  args.skip_unhandled_events = true;
  esp_timer_create(&args, handle);
}

// VSYNC falling edge: start gate scan from row 0
static void ARDUINO_ISR_ATTR vsync_isr() {
  if (!enabled) return;
  digitalWrite(GSPU_OUT, HIGH);
  esp_timer_start_once(gspu_timer, GSPU_US);
}

// HSYNC falling edge: advance source and gate drivers one row
static void ARDUINO_ISR_ATTR hsync_isr() {
  if (!enabled) return;
  // Source start pulse — tells source IC to begin clocking in pixel data
  digitalWrite(SSPL_OUT, HIGH);
  esp_timer_start_once(sspl_timer, SSPL_US);

  // Gate output enable — holds gate row active while source data settles
  digitalWrite(GOE_OUT, LOW);
  esp_timer_start_once(goe_timer, GOE_US);

  // Polarity inversion — AC drive, alternate every line
  pol_state = !pol_state;
  digitalWrite(POL_OUT, pol_state);
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200, SERIAL_8N1, A0, D13);  // RX=A0, TX=D13 (reserved, unused)

  pinMode(VSYNC_IN, INPUT);
  pinMode(HSYNC_IN, INPUT);
  pinMode(GSPU_OUT, OUTPUT);
  pinMode(SSPL_OUT, OUTPUT);
  pinMode(GOE_OUT,  OUTPUT);
  pinMode(POL_OUT,  OUTPUT);

  digitalWrite(GSPU_OUT, LOW);
  digitalWrite(SSPL_OUT, LOW);
  digitalWrite(GOE_OUT,  HIGH);  // active-low: start disabled
  digitalWrite(POL_OUT,  LOW);

  create_isr_timer(gspu_end, &gspu_timer);
  create_isr_timer(sspl_end, &sspl_timer);
  create_isr_timer(goe_end,  &goe_timer);

  // GSC: continuous 50% PWM via hardware LEDC (channel 0)
  ledcSetup(0, GSC_HZ, 8);
  ledcAttachPin(GSC_OUT, 0);
  ledcWrite(0, 128);

  attachInterrupt(digitalPinToInterrupt(VSYNC_IN), vsync_isr, FALLING);
  attachInterrupt(digitalPinToInterrupt(HSYNC_IN), hsync_isr, FALLING);
}

void loop() {
  // Handle Pi commands
  while (Serial1.available()) {
    char cmd = Serial1.read();
    if (cmd == 'e') {
      enabled = true;
      ledcWrite(0, 128);
    } else if (cmd == 'd') {
      enabled = false;
      ledcWrite(0, 0);
      digitalWrite(GSPU_OUT, LOW);
      digitalWrite(SSPL_OUT, LOW);
      digitalWrite(GOE_OUT,  HIGH);
    }
  }

  // Poll touch at ~50 Hz
  static unsigned long last_touch_ms = 0;
  static bool was_touched = false;

  unsigned long now = millis();
  if (now - last_touch_ms >= TOUCH_INTERVAL_MS) {
    last_touch_ms = now;

    if (touch_detect()) {
      TouchPoint tp = touch_read();
      Serial.printf("T %d %d\n", tp.x, tp.y);
      was_touched = true;
    } else if (was_touched) {
      Serial.print("U\n");
      was_touched = false;
    }
  }
}
