/*
 * Touch calibration sketch for LA070WV1-TD01 resistive overlay
 * Target: Arduino Nano ESP32
 *
 * Walks through 4 corners, records min/max ADC values, then prints
 * calibration #defines ready to paste into toyota_display.ino.
 *
 * Wiring (same as toyota_display):
 *   A2 ↔ Touch A+  adapter pin 1
 *   A1 ↔ Touch B+  adapter pin 3
 *   D11 ↔ Touch A− adapter pin 5
 *   D10 ↔ Touch B− adapter pin 7
 */

#define TOUCH_AP  A2
#define TOUCH_BP  A1
#define TOUCH_AN  D11
#define TOUCH_BN  D10

#define TOUCH_SAMPLES    16
#define TOUCH_SETTLE_US 100
#define TOUCH_THRESHOLD 200

struct RawPoint { int a; int b; };

static int adc_average(int pin) {
  long sum = 0;
  for (int i = 0; i < TOUCH_SAMPLES; i++) sum += analogRead(pin);
  return (int)(sum / TOUCH_SAMPLES);
}

static bool touch_detect() {
  pinMode(TOUCH_AP, OUTPUT); digitalWrite(TOUCH_AP, HIGH);
  pinMode(TOUCH_AN, OUTPUT); digitalWrite(TOUCH_AN, LOW);
  pinMode(TOUCH_BP, INPUT_PULLDOWN);
  pinMode(TOUCH_BN, INPUT);
  delayMicroseconds(TOUCH_SETTLE_US);
  return adc_average(TOUCH_BP) > TOUCH_THRESHOLD;
}

static RawPoint touch_read() {
  // read A+ while driving B
  pinMode(TOUCH_BP, OUTPUT); digitalWrite(TOUCH_BP, HIGH);
  pinMode(TOUCH_BN, OUTPUT); digitalWrite(TOUCH_BN, LOW);
  pinMode(TOUCH_AP, INPUT);
  pinMode(TOUCH_AN, INPUT);
  delayMicroseconds(TOUCH_SETTLE_US);
  int a = adc_average(TOUCH_AP);

  // read B+ while driving A
  pinMode(TOUCH_AP, OUTPUT); digitalWrite(TOUCH_AP, HIGH);
  pinMode(TOUCH_AN, OUTPUT); digitalWrite(TOUCH_AN, LOW);
  pinMode(TOUCH_BP, INPUT);
  pinMode(TOUCH_BN, INPUT);
  delayMicroseconds(TOUCH_SETTLE_US);
  int b = adc_average(TOUCH_BP);

  return {a, b};
}

#define COLLECT_MS 5000  // sampling window per corner in milliseconds

// Collect the extreme values for one corner over a fixed time window.
// want_min_a: true = track minimum A (top corners), false = maximum (bottom corners)
// want_min_b: true = track minimum B (right corners), false = maximum (left corners)
static RawPoint collect_corner(const char* label, bool want_min_a, bool want_min_b) {
  Serial.printf("\nRoll your finger around the %s corner (%d sec)...\n", label, COLLECT_MS / 1000);

  // wait for first touch before starting the clock
  while (!touch_detect()) delay(20);

  int best_a = want_min_a ? INT_MAX : INT_MIN;
  int best_b = want_min_b ? INT_MAX : INT_MIN;
  int count = 0;
  unsigned long start = millis();

  while (millis() - start < COLLECT_MS) {
    if (touch_detect()) {
      RawPoint p = touch_read();
      if (p.a > TOUCH_THRESHOLD && p.b > TOUCH_THRESHOLD) {
        best_a = want_min_a ? min(best_a, p.a) : max(best_a, p.a);
        best_b = want_min_b ? min(best_b, p.b) : max(best_b, p.b);
        count++;
      }
    }
    delay(20);
  }

  Serial.printf("  → A=%d  B=%d  (%d samples)\n", best_a, best_b, count);
  delay(3000);
  return {best_a, best_b};
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("=== Touch Calibration ===");
  Serial.println("Touch each corner when prompted. Hold still, then lift.\n");
  delay(2000);

  RawPoint tl = collect_corner("TOP LEFT",     true,  false);
  RawPoint tr = collect_corner("TOP RIGHT",    true,  true);
  RawPoint bl = collect_corner("BOTTOM LEFT",  false, false);
  RawPoint br = collect_corner("BOTTOM RIGHT", false, true);

  int cal_y_top    = (tl.a + tr.a) / 2;
  int cal_y_bottom = (bl.a + br.a) / 2;
  int cal_x_left   = (tl.b + bl.b) / 2;
  int cal_x_right  = (tr.b + br.b) / 2;

  Serial.println("\n=== Calibration Result ===");
  Serial.println("Paste these into toyota_display.ino:\n");
  Serial.printf("#define CAL_Y_TOP     %d\n", cal_y_top);
  Serial.printf("#define CAL_Y_BOTTOM  %d\n", cal_y_bottom);
  Serial.printf("#define CAL_X_LEFT    %d\n", cal_x_left);
  Serial.printf("#define CAL_X_RIGHT   %d\n", cal_x_right);
}

void loop() {}
