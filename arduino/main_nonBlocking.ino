/* Non-blocking ultrasonic + motor/servo/encoder full sketch
   Outputs telemetry: "lane motion Rdistance Ldistance arduino_fps is_moving_with_pulse"
   - Rdistance = right sensor (cm) or -1 if no echo
   - Ldistance = left sensor (cm) or -1 if no echo
   - arduino_fps = real loop() frequency (Hz)
   - is_moving_with_pulse = 1 if currently moving by pulses, 0 otherwise
*/

#include <Servo.h>
#include <ctype.h>
#include <PulseQueue.h>
#include "Encoder.h"

/* =========================
   CONFIG
   ========================= */
const unsigned long ULTRA_INTERVAL_MS = 120UL;   // how often each ultrasonic sensor is sampled (ms)
const unsigned long ULTRA_TIMEOUT_US  = 30000UL; // 30 ms timeout for echo
const unsigned long STATUS_INTERVAL_MS = 50UL;  // how often we print telemetry (ms)

/* =========================
   MOTOR PINS
   ========================= */
int IN1 = 10;
int M1  = 12;
int IN2 = 11;
int M2  = 13;

/* =========================
   SERVO
   ========================= */
Servo myServo;
int SERVO_PIN = 9;
int servoCurrent = 90;
const int SERVO_MIN = 10;
const int SERVO_MAX = 170;

/* =========================
   ENCODER
   ========================= */
const int REED_PIN = 2;
const unsigned long DEBOUNCE_US = 5000UL;   // HALL: 5000, LASER: 0
Encoder encoder(REED_PIN, DEBOUNCE_US, FALLING);

/* =========================
   ULTRASONIC PINS (user layout)
   ========================= */
const int ULTRA_LEFT_TRIG  = 4;
const int ULTRA_LEFT_ECHO  = 5;
const int ULTRA_RIGHT_TRIG = 6;
const int ULTRA_RIGHT_ECHO = 7;
const int ULTRA_SIDE_TRIG  = 8;
const int ULTRA_SIDE_ECHO  = 24; // ensure this pin is available on your board

const int STOP_DISTANCE_CM = 35;
const int SIDE_RETURN_DISTANCE_CM = 20;

/* =========================
   NON-BLOCKING ULTRASONIC SENSOR
   =========================
   Small state machine:
     IDLE -> TRIGGER (10us pulse) -> WAIT_ECHO (poll echo pin for rising/falling)
   On timeout or on falling edge, produce distance (cm) or -1 for no echo.
*/
enum USState { US_IDLE=0, US_WAITING_ECHO };

struct NBUltrasonic {
  int trigPin;
  int echoPin;
  USState state;
  unsigned long lastReadMs;
  unsigned long triggerMicros;     // micros() when triggered
  unsigned long waitingStartMicros;
  unsigned long echoStartMicros;
  int distanceCm;                  // -1 = invalid/no-echo, else cm
  unsigned long timeoutUs;
  unsigned long intervalMs;        // how often to trigger
  NBUltrasonic() {}
  void begin(int tPin, int ePin, unsigned long timeout_us, unsigned long interval_msec) {
    trigPin = tPin;
    echoPin = ePin;
    timeoutUs = timeout_us;
    intervalMs = interval_msec;
    state = US_IDLE;
    lastReadMs = 0;
    distanceCm = -1;
    pinMode(trigPin, OUTPUT);
    pinMode(echoPin, INPUT);
    digitalWrite(trigPin, LOW);
  }
  void update(unsigned long nowMs) {
    // If currently idle and it's time, trigger the sensor.
    if (state == US_IDLE) {
      if ((long)(nowMs - lastReadMs) >= (long)intervalMs) {
        // trigger with a short 10us pulse (blocking but tiny)
        digitalWrite(trigPin, LOW);
        delayMicroseconds(2);
        digitalWrite(trigPin, HIGH);
        delayMicroseconds(10);
        digitalWrite(trigPin, LOW);
        // start waiting
        waitingStartMicros = micros();
        echoStartMicros = 0;
        state = US_WAITING_ECHO;
      }
    } else if (state == US_WAITING_ECHO) {
      unsigned long nowUs = micros();
      // detect rising edge (start) and falling edge (end)
      int echoVal = digitalRead(echoPin);
      if (echoStartMicros == 0) {
        if (echoVal == HIGH) {
          echoStartMicros = nowUs;
        } else {
          // still waiting for rising edge
        }
      } else {
        // we have start; wait for falling edge
        if (echoVal == LOW) {
          unsigned long echoEnd = nowUs;
          unsigned long durationUs = echoEnd - echoStartMicros;
          // distance in cm = duration_us / 58 (approx)
          int cm = (int)(durationUs / 58UL);
          if (cm <= 0) cm = -1;
          distanceCm = cm;
          lastReadMs = millis();
          state = US_IDLE;
        } else {
          // still in HIGH
        }
      }
      // timeout handling
      if ((nowUs - waitingStartMicros) >= timeoutUs) {
        distanceCm = -1; // no echo
        lastReadMs = millis();
        state = US_IDLE;
      }
    }
  }
  int getCm() { return distanceCm; }
};

/* =========================
   OBJECTS
   ========================= */
NBUltrasonic ultraLeft;
NBUltrasonic ultraRight;
NBUltrasonic ultraSide;

/* =========================
   MOTOR STATE
   ========================= */
bool movingByPulses = false;
int targetPulses = 0;
int currentMotorSpeed = 0;
int motorDirection = 1;

/* =========================
   PULSE QUEUE
   ========================= */
PulseQueue queue(16);

/* =========================
   LANE LOGIC
   ========================= */
bool lane_changing_mode = true;
char lane = 'R';

enum LaneState {
  LANE_NORMAL = 0,
  LANE_LEFT,
  LANE_RETURNING
};

LaneState laneState = LANE_NORMAL;
unsigned long laneChangeStart = 0;

/* =========================
   SERIAL INPUT
   ========================= */
String inputString = "";
bool stringComplete = false;

/* =========================
   LOOP FREQUENCY (REAL)
   ========================= */
unsigned long loopCounter = 0;
unsigned long lastLoopHzTime = 0;
unsigned int loopHz = 0;

/* =========================
   TELEMETRY
   ========================= */
unsigned long lastStatusSend = 0;

/* =========================
   FUNCTION DECLARATIONS
   ========================= */
void stopMotor();
void startServoMoveImmediate(int target);
void startMotorByPulses(char dirChar, int speedVal, int pulses, int servoAngle);
void startLaneChangeLeft();
void startReturnToRightLane();
void finishLaneReturn();
bool looksLikePulseGroups(const String &line);
char motionChar();
void sendStatus();

/* =========================
   SETUP
   ========================= */
void setup() {
  Serial.begin(115200);
  while (!Serial) {}

  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(M1, OUTPUT);
  pinMode(M2, OUTPUT);

  encoder.begin();

  // init non-blocking ultrasonic sensors
  ultraLeft.begin(ULTRA_LEFT_TRIG, ULTRA_LEFT_ECHO, ULTRA_TIMEOUT_US, ULTRA_INTERVAL_MS);
  ultraRight.begin(ULTRA_RIGHT_TRIG, ULTRA_RIGHT_ECHO, ULTRA_TIMEOUT_US, ULTRA_INTERVAL_MS);
  ultraSide.begin(ULTRA_SIDE_TRIG, ULTRA_SIDE_ECHO, ULTRA_TIMEOUT_US, ULTRA_INTERVAL_MS);

  myServo.attach(SERVO_PIN);
  myServo.write(servoCurrent);

  lastLoopHzTime = millis();
}

/* =========================
   HELPERS
   ========================= */
int getPulseCount() {
  return encoder.getCount();
}

void resetPulseCount() {
  encoder.reset();
}

void setMotorSpeed(int speed) {
  int dir;
  if (speed > 255) speed = 255;
  if (speed < -255) speed = -255;

  if (speed >= 0) dir = HIGH;
  else { dir = LOW; speed = -speed; }

  analogWrite(IN1, speed);
  analogWrite(IN2, speed);
  digitalWrite(M1, dir);
  digitalWrite(M2, dir);

  currentMotorSpeed = (dir == HIGH) ? speed : -speed;
}

void stopMotor() {
  analogWrite(IN1, 0);
  analogWrite(IN2, 0);
  digitalWrite(M1, LOW);
  digitalWrite(M2, LOW);
  movingByPulses = false;
  currentMotorSpeed = 0;
}

void startServoMoveImmediate(int target) {
  if (target < SERVO_MIN) target = SERVO_MIN;
  if (target > SERVO_MAX) target = SERVO_MAX;
  myServo.write(target);
  servoCurrent = target;
}

void startMotorByPulses(char dirChar, int speedVal, int pulses, int servoAngle) {
  noInterrupts();
  resetPulseCount();
  interrupts();

  targetPulses = pulses;
  movingByPulses = true;
  motorDirection = (tolower(dirChar) == 'f') ? 1 : -1;

  setMotorSpeed(speedVal * motorDirection);
  startServoMoveImmediate(servoAngle);
}

/* =========================
   LANE FUNCTIONS
   ========================= */
void startLaneChangeLeft() {
  if (laneState != LANE_NORMAL) return;
  queue.clear();
  queue.parseAndEnqueue("b 255 4 50 b 255 3 130");
  laneState = LANE_LEFT;
  lane = 'L';
  laneChangeStart = millis();
}

void startReturnToRightLane() {
  if (laneState == LANE_RETURNING) return;
  queue.clear();
  queue.parseAndEnqueue("f 255 3 130 f 255 3 50");
  laneState = LANE_RETURNING;
  laneChangeStart = millis();
}

void finishLaneReturn() {
  laneState = LANE_NORMAL;
  lane = 'R';
}

/* =========================
   TELEMETRY HELPERS
   ========================= */
char motionChar() {
  if (currentMotorSpeed == 0) return 'S';
  if (currentMotorSpeed > 0) return 'F';
  return 'B';
}

void sendStatus() {
  int rdist = ultraRight.getCm();
  int ldist = ultraLeft.getCm();

  // Print exactly as requested:
  // lane motion Rdistance Ldistance arduino_fps is_moving_with_pulse
  Serial.print(lane);
  Serial.print(' ');
  Serial.print(motionChar());
  Serial.print(' ');
  Serial.print(rdist);       // right distance first (Rdistance)
  Serial.print(' ');
  Serial.print(ldist);       // left distance next (Ldistance)
  Serial.print(' ');
  Serial.print(loopHz);
  Serial.print(' ');
  Serial.println(movingByPulses ? 1 : 0);
}

/* =========================
   MAIN LOOP
   ========================= */
void loop() {
  // count loop iterations to compute real loop frequency
  loopCounter++;
  unsigned long nowMs = millis();
  if (nowMs - lastLoopHzTime >= 1000UL) {
    loopHz = (unsigned int)loopCounter;
    loopCounter = 0;
    lastLoopHzTime = nowMs;
  }

  // update ultrasonic sensors (non-blocking)
  // Trigger/update left and right every ULTRA_INTERVAL_MS.
  // Side sensor only when not movingByPulses to save work.
  ultraLeft.update(nowMs);
  ultraRight.update(nowMs);
  if (!movingByPulses) ultraSide.update(nowMs);

  // Serial input handling (serialEvent() will also add to inputString)
  if (stringComplete) {
    inputString.trim();
    String work = inputString;

    if (movingByPulses && looksLikePulseGroups(work)) {
      queue.parseAndEnqueue(work);
    }
    else if (work.equalsIgnoreCase("stop")) {
      queue.clear();
      stopMotor();
    }
    else if (work.startsWith("motor ")) {
      setMotorSpeed(work.substring(6).toInt());
    }
    else if (work.startsWith("servo ")) {
      startServoMoveImmediate(work.substring(6).toInt());
    }
    else {
      queue.parseAndEnqueue(work);
    }

    inputString = "";
    stringComplete = false;
  }

  // Read the side distance value for lane-return decision (non-blocking get)
  int distSide = ultraSide.getCm();

  // Obstacle check: treat only positive non-negative distances as valid
  int dl = ultraLeft.getCm();
  int dr = ultraRight.getCm();
  bool obstacle = (dl > 0 && dl <= STOP_DISTANCE_CM) || (dr > 0 && dr <= STOP_DISTANCE_CM);

  if (lane == 'R' && obstacle) {
    if (!lane_changing_mode) {
      stopMotor();
      queue.clear();
      startServoMoveImmediate(90);
    } else if (laneState == LANE_NORMAL) {
      startLaneChangeLeft();
    }
  }

  if (laneState == LANE_LEFT && !movingByPulses && (distSide > 0 && distSide <= SIDE_RETURN_DISTANCE_CM)) {
    startReturnToRightLane();
  }

  if (laneState == LANE_RETURNING && millis() - laneChangeStart >= 1000UL) {
    finishLaneReturn();
  }

  if (!movingByPulses && queue.count() > 0) {
    PulseCmd cmd;
    if (queue.dequeue(cmd)) {
      startMotorByPulses(cmd.dir, cmd.speed, cmd.pulses, cmd.angle);
    }
  }

  if (movingByPulses && getPulseCount() >= targetPulses) {
    stopMotor();
    startServoMoveImmediate(90);
  }

  if (millis() - lastStatusSend >= STATUS_INTERVAL_MS) {
    lastStatusSend = millis();
    sendStatus();
  }

  // small yield to avoid completely tight loop
  delay(1);
}

/* =========================
   SERIAL EVENT
   ========================= */
void serialEvent() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputString.length()) stringComplete = true;
    } else {
      inputString += c;
    }
  }
}

/* =========================
   PARSER CHECK
   ========================= */
bool looksLikePulseGroups(const String &line) {
  if (line.length() == 0) return false;
  char c = tolower(line.charAt(0));
  return (c == 'f' || c == 'b');
}
