/*
    * HC-SR04 example - code adapted from 
    * This code measures distance using the HC-SR04 ultrasonic sensor
    * and lights up an LED if an object is closer than 25 cm.
    * For the fritzing see diagram in the repository.
*/

// Pin definitions
const int trigPin = 9;
const int echoPin = 10;
const int ledPin = 8; // LED connected to light red
const int ledPinyellow = 12; // LED connected to light yellow

// Variables for duration and distance
float duration, distance;

// Setup function
void setup() {
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  pinMode(ledPin, OUTPUT);
  pinMode(ledPinyellow, OUTPUT);
  Serial.begin(9600); // Start serial communication at 9600 baud
}

// Main loop
void loop() {
  // Trigger the sensor to send out ultrasonic pulse
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  // Read the echo time
  duration = pulseIn(echoPin, HIGH);

  // Calculate distance in centimeters
  distance = (duration * 0.0343) / 2;

  // Print distance to Serial Monitor
  Serial.print("Distance: ");
  Serial.print(distance);
  Serial.println(" cm");

  // Turn LED on if distance < 10 cm, else turn off
  if (distance <= 25) {
    digitalWrite(ledPin, HIGH);
    digitalWrite(ledPinyellow, LOW);
  }
  else if (distance > 25 && distance <= 50) {
      digitalWrite(ledPinyellow, HIGH);
      digitalWrite(ledPin, LOW);
  }
  else {
    digitalWrite(ledPinyellow, LOW);
    digitalWrite(ledPin, LOW);
  }
  delay(100); // Short delay before next measurement
}