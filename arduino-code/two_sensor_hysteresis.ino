/*
 * HC-SR04 with Hysteresis Filter + LED Indicator Example
 * 
 * Demonstrates how hysteresis prevents rapid on/off switching
 * when a measurement hovers near a threshold.
 * 
 * LEDs on pin 2 and 4 turns ON when object is in range (close)
 * 
 * USE CASE: Proximity detection with stable output
 */

const int trigPin1 = 7;
const int echoPin1 = 8;
const int ledPin1 = 2;

const int trigPin2 = 12;
const int echoPin2 = 13;
const int ledPin2 = 4;

float duration_1, duration_2, distance_1, distance_2;

const float LOWER_THRESHOLD = 30.0;
const float UPPER_THRESHOLD = 40.0;

bool is_close_1 = false;
bool is_close_2 = false;

// Hysteresis filter (pass variable by reference!)
bool hysteresis_filter(float input, bool &state) {
  if (state) {
    if (input > UPPER_THRESHOLD) state = false;
  } else {
    if (input < LOWER_THRESHOLD) state = true;
  }
  return state;
}

float readDistance(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  // timeout = 25,000 µs (~4m max distance)
  long duration = pulseIn(echoPin, HIGH, 25000);
  return (duration * 0.0343) / 2.0;
}

void setup() {
  pinMode(trigPin1, OUTPUT);
  pinMode(echoPin1, INPUT);
  pinMode(ledPin1, OUTPUT);

  pinMode(trigPin2, OUTPUT);
  pinMode(echoPin2, INPUT);
  pinMode(ledPin2, OUTPUT);

  Serial.begin(115200);
  Serial.println("Dist1,State1,Dist2,State2,Lower,Upper");
}

void loop() {
  // --- Sensor 1 ---
  distance_1 = readDistance(trigPin1, echoPin1);
  bool state1 = hysteresis_filter(distance_1, is_close_1);
  digitalWrite(ledPin1, state1 ? HIGH : LOW);

  delay(50);  // give sound time to dissipate before next sensor

  // --- Sensor 2 ---
  distance_2 = readDistance(trigPin2, echoPin2);
  bool state2 = hysteresis_filter(distance_2, is_close_2);
  digitalWrite(ledPin2, state2 ? HIGH : LOW);

  // --- Serial output ---
  Serial.print(distance_1);
  Serial.print(",");
  Serial.print(state1 ? 50 : 0);
  Serial.print(",");
  Serial.print(distance_2);
  Serial.print(",");
  Serial.print(state2 ? 50 : 0);
  Serial.print(",");
  Serial.print(LOWER_THRESHOLD);
  Serial.print(",");
  Serial.println(UPPER_THRESHOLD);

  delay(100);
}