#include <Servo.h>
#include <ctype.h>
#include <PulseQueue.h>
#include "Encoder.h"

/* =========================
CONFIG
========================= */
const unsigned long ULTRA_INTERVAL_MS = 120UL;
const unsigned long ULTRA_TIMEOUT_US  = 30000UL;
const unsigned long STATUS_INTERVAL_MS = 50UL;

/* =========================
TM1638 PINS
========================= */
const int TM_STB_PIN = 26;
const int TM_CLK_PIN = 28;
const int TM_DIO_PIN = 30;

/* TM1638 keys
K1 -> force stop
K2 -> resume serial control
If your module wiring/key order differs, swap these two bits.
*/
const uint8_t TM_FORCE_STOP_KEY_BIT = 0; // K1
const uint8_t TM_RESUME_KEY_BIT     = 7; // K2

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
const int SERVO_CENTER = 90;

/* =========================
ENCODER
========================= */
const int REED_PIN = 2;
const unsigned long DEBOUNCE_US = 0;
Encoder encoder(REED_PIN, DEBOUNCE_US, FALLING);

/* =========================
ULTRASONIC PINS
========================= */
const int ULTRA_LEFT_TRIG  = 4;
const int ULTRA_LEFT_ECHO  = 5;
const int ULTRA_RIGHT_TRIG = 6;
const int ULTRA_RIGHT_ECHO = 7;
const int ULTRA_SIDE_TRIG  = 8;
const int ULTRA_SIDE_ECHO  = 24;

const int STOP_DISTANCE_CM = 35;
const int SIDE_RETURN_DISTANCE_CM = 20;

/* =========================
TM1638 DRIVER
========================= */
class TM1638Panel {
public:
  enum PanelMode {
    MODE_CLEAR = 0,
    MODE_STOP,
    MODE_LEFT,
    MODE_RIGHT,
    MODE_ALL_ON,
    MODE_FORCE_STOP
  };

  void begin(uint8_t stb, uint8_t clk, uint8_t dio) {
    stbPin = stb;
    clkPin = clk;
    dioPin = dio;

    pinMode(stbPin, OUTPUT);
    pinMode(clkPin, OUTPUT);
    pinMode(dioPin, OUTPUT);

    digitalWrite(stbPin, HIGH);
    digitalWrite(clkPin, HIGH);
    digitalWrite(dioPin, HIGH);

    blinkEnabled = false;
    blinkVisible = true;
    blinkMask = 0;
    baseLedMask = 0;
    blinkPeriodMs = 250;
    lastBlinkMs = millis();
    mode = MODE_CLEAR;
    dirty = true;

    renderMode();
    setBrightness(7);
    flush();
  }

  void update() {
    if (blinkEnabled) {
      unsigned long now = millis();
      if (now - lastBlinkMs >= blinkPeriodMs) {
        lastBlinkMs = now;
        blinkVisible = !blinkVisible;
        dirty = true;
      }
    }

    if (dirty) {
      flush();
    }
  }

  void setStop() {
    mode = MODE_STOP;
    blinkEnabled = false;
    blinkVisible = true;
    blinkMask = 0;
    renderMode();
    dirty = true;
  }

  void setForceStop() {
    mode = MODE_FORCE_STOP;
    blinkEnabled = false;
    blinkVisible = true;
    blinkMask = 0;
    renderMode();
    dirty = true;
  }

  void setLeft() {
    mode = MODE_LEFT;
    blinkEnabled = true;
    blinkVisible = true;
    blinkMask = 0x07;   // LED1, LED2, LED3
    blinkPeriodMs = 250;
    renderMode();
    dirty = true;
  }

  void setRight() {
    mode = MODE_RIGHT;
    blinkEnabled = true;
    blinkVisible = true;
    blinkMask = 0xE0;   // LED6, LED7, LED8
    blinkPeriodMs = 250;
    renderMode();
    dirty = true;
  }

  void clearPanel() {
    mode = MODE_CLEAR;
    blinkEnabled = false;
    blinkVisible = true;
    blinkMask = 0;
    baseLedMask = 0;
    blankDisplay();
    dirty = true;
  }

  void allLedsOn() {
    mode = MODE_ALL_ON;
    blinkEnabled = false;
    blinkVisible = true;
    blinkMask = 0;
    baseLedMask = 0xFF;
    blankDisplay();
    dirty = true;
  }

  uint8_t readButtons() {
    uint8_t buttons = 0;

    digitalWrite(stbPin, LOW);
    writeByte(0x42);          // key scan command
    pinMode(dioPin, INPUT_PULLUP);

    for (uint8_t i = 0; i < 4; i++) {
      uint8_t v = readByte();

      // Decode 4x2 key matrix into 8 bits:
      // row i: bit0 -> K(2*i+1), bit4 -> K(2*i+2)
      buttons |= ((v & 0x01) ? 1 : 0) << (i * 2);
      buttons |= ((v & 0x10) ? 1 : 0) << (i * 2 + 1);
    }

    digitalWrite(stbPin, HIGH);
    pinMode(dioPin, OUTPUT);
    digitalWrite(dioPin, HIGH);

    return buttons;
  }

private:
  uint8_t stbPin = 0;
  uint8_t clkPin = 0;
  uint8_t dioPin = 0;

  uint8_t displayBuf[8] = {0};
  uint8_t baseLedMask = 0;
  uint8_t blinkMask = 0;

  bool blinkEnabled = false;
  bool blinkVisible = true;
  bool dirty = false;
  unsigned long blinkPeriodMs = 250;
  unsigned long lastBlinkMs = 0;

  PanelMode mode = MODE_CLEAR;

  void blankDisplay() {
    for (uint8_t i = 0; i < 8; i++) {
      displayBuf[i] = 0x00;
    }
  }

  void renderMode() {
    blankDisplay();

    switch (mode) {
      case MODE_CLEAR:
        baseLedMask = 0x00;
        break;

      case MODE_STOP:
      case MODE_FORCE_STOP:
        putWordAt(2, "STOP");
        baseLedMask = 0xFF;
        break;

      case MODE_LEFT:
        putWordAt(0, "LEFT");
        baseLedMask = 0x00;
        break;

      case MODE_RIGHT:
        putWordAt(3, "RIGHT");
        baseLedMask = 0x00;
        break;

      case MODE_ALL_ON:
        baseLedMask = 0xFF;
        break;
    }
  }

  void putWordAt(uint8_t startPos, const char *text) {
    for (uint8_t i = 0; i < 8 && text[i] != '\0'; i++) {
      uint8_t pos = startPos + i;
      if (pos < 8) {
        displayBuf[pos] = segForChar(text[i]);
      }
    }
  }

  static uint8_t segForChar(char c) {
    switch (toupper((unsigned char)c)) {
      case '0': return 0x3F;
      case '1': return 0x06;
      case '2': return 0x5B;
      case '3': return 0x4F;
      case '4': return 0x66;
      case '5': return 0x6D;
      case '6': return 0x7D;
      case '7': return 0x07;
      case '8': return 0x7F;
      case '9': return 0x6F;

      case 'A': return 0x77;
      case 'B': return 0x7C;
      case 'C': return 0x39;
      case 'D': return 0x5E;
      case 'E': return 0x79;
      case 'F': return 0x71;
      case 'G': return 0x3D;
      case 'H': return 0x76;
      case 'I': return 0x06;
      case 'J': return 0x1E;
      case 'L': return 0x38;
      case 'N': return 0x54;
      case 'O': return 0x3F;
      case 'P': return 0x73;
      case 'R': return 0x50;
      case 'S': return 0x6D;
      case 'T': return 0x78;
      case 'U': return 0x3E;
      case 'Y': return 0x6E;

      case '-': return 0x40;
      case '_': return 0x08;
      case ' ': return 0x00;
      default:  return 0x00;
    }
  }

  void setBrightness(uint8_t b) {
    b &= 0x07;
    sendCommand(0x88 | b);
  }

  void sendCommand(uint8_t cmd) {
    digitalWrite(stbPin, LOW);
    writeByte(cmd);
    digitalWrite(stbPin, HIGH);
  }

  void writeByte(uint8_t data) {
    for (uint8_t i = 0; i < 8; i++) {
      digitalWrite(clkPin, LOW);
      digitalWrite(dioPin, (data & 0x01) ? HIGH : LOW);
      delayMicroseconds(1);
      digitalWrite(clkPin, HIGH);
      delayMicroseconds(1);
      data >>= 1;
    }
  }

  uint8_t readByte() {
    uint8_t value = 0;

    for (uint8_t i = 0; i < 8; i++) {
      digitalWrite(clkPin, LOW);
      delayMicroseconds(1);
      if (digitalRead(dioPin)) {
        value |= (1 << i);
      }
      digitalWrite(clkPin, HIGH);
      delayMicroseconds(1);
    }

    return value;
  }

  void flush() {
    // write mode: auto increment
    sendCommand(0x40);

    digitalWrite(stbPin, LOW);
    writeByte(0xC0);

    for (uint8_t i = 0; i < 8; i++) {
      bool ledOn = ((baseLedMask >> i) & 0x01) != 0;
      bool blinkOn = blinkEnabled && blinkVisible && (((blinkMask >> i) & 0x01) != 0);
      uint8_t ledVal = (ledOn || blinkOn) ? 0x01 : 0x00;

      writeByte(displayBuf[i]);
      writeByte(ledVal);
    }

    digitalWrite(stbPin, HIGH);
    dirty = false;
  }
};

TM1638Panel panel;

/* =========================
NON-BLOCKING ULTRASONIC SENSOR
========================= */
enum USState { US_IDLE = 0, US_WAITING_ECHO };

struct NBUltrasonic {
  int trigPin;
  int echoPin;
  USState state;
  unsigned long lastReadMs;
  unsigned long waitingStartMicros;
  unsigned long echoStartMicros;
  int distanceCm;
  unsigned long timeoutUs;
  unsigned long intervalMs;

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
    if (state == US_IDLE) {
      if ((long)(nowMs - lastReadMs) >= (long)intervalMs) {
        digitalWrite(trigPin, LOW);
        delayMicroseconds(2);
        digitalWrite(trigPin, HIGH);
        delayMicroseconds(10);
        digitalWrite(trigPin, LOW);

        waitingStartMicros = micros();
        echoStartMicros = 0;
        state = US_WAITING_ECHO;
      }
    } else if (state == US_WAITING_ECHO) {
      unsigned long nowUs = micros();
      int echoVal = digitalRead(echoPin);

      if (echoStartMicros == 0) {
        if (echoVal == HIGH) {
          echoStartMicros = nowUs;
        }
      } else {
        if (echoVal == LOW) {
          unsigned long durationUs = nowUs - echoStartMicros;
          int cm = (int)(durationUs / 58UL);
          if (cm <= 0) cm = -1;
          distanceCm = cm;
          lastReadMs = millis();
          state = US_IDLE;
        }
      }

      if ((nowUs - waitingStartMicros) >= timeoutUs) {
        distanceCm = -1;
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
SERIAL / CONTROL STATE
========================= */
String inputString = "";
bool stringComplete = false;
bool emergencyStopActive = false;
uint8_t lastKeyMask = 0;

/* =========================
LOOP FREQUENCY
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
void enterForceStop();
void exitForceStop();
void clearSerialBuffers();
void handleTmButtons();

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

  ultraLeft.begin(ULTRA_LEFT_TRIG, ULTRA_LEFT_ECHO, ULTRA_TIMEOUT_US, ULTRA_INTERVAL_MS);
  ultraRight.begin(ULTRA_RIGHT_TRIG, ULTRA_RIGHT_ECHO, ULTRA_TIMEOUT_US, ULTRA_INTERVAL_MS);
  ultraSide.begin(ULTRA_SIDE_TRIG, ULTRA_SIDE_ECHO, ULTRA_TIMEOUT_US, ULTRA_INTERVAL_MS);

  myServo.attach(SERVO_PIN);
  myServo.write(servoCurrent);

  panel.begin(TM_STB_PIN, TM_CLK_PIN, TM_DIO_PIN);
  panel.clearPanel();

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
  motorDirection = (tolower((unsigned char)dirChar) == 'f') ? 1 : -1;

  setMotorSpeed(speedVal * motorDirection);
  startServoMoveImmediate(servoAngle);
}

/* =========================
FORCE STOP / RESUME
========================= */
void clearSerialBuffers() {
  // Only used for hard stops now, clearing out pending instructions
  inputString = "";
  stringComplete = false;

  while (Serial.available()) {
    Serial.read();
  }
}

void enterForceStop() {
  emergencyStopActive = true;

  queue.clear();
  stopMotor();
  targetPulses = 0;
  laneState = LANE_NORMAL;
  lane = 'R';
  laneChangeStart = 0;

  startServoMoveImmediate(SERVO_CENTER);

  clearSerialBuffers();
  panel.setForceStop();
}

void exitForceStop() {
  emergencyStopActive = false;
  clearSerialBuffers();
  panel.clearPanel();
}

/* =========================
TM1638 BUTTON HANDLING
========================= */
void handleTmButtons() {
  uint8_t keys = panel.readButtons();
  uint8_t rising = keys & ~lastKeyMask;
  lastKeyMask = keys;

  if (rising & (1 << TM_FORCE_STOP_KEY_BIT)) {
    enterForceStop();
  }

  if (rising & (1 << TM_RESUME_KEY_BIT)) {
    exitForceStop();
  }
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

  panel.setLeft();
}

void startReturnToRightLane() {
  if (laneState == LANE_RETURNING) return;
  queue.clear();
  queue.parseAndEnqueue("f 255 3 130 f 255 3 50");
  laneState = LANE_RETURNING;
  laneChangeStart = millis();

  panel.setRight();
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

  Serial.print(lane);
  Serial.print(' ');
  Serial.print(motionChar());
  Serial.print(' ');
  Serial.print(rdist);
  Serial.print(' ');
  Serial.print(ldist);
  Serial.print(' ');
  Serial.print(loopHz);
  Serial.print(' ');
  Serial.println(movingByPulses ? 1 : 0);
}

/* =========================
MAIN LOOP
========================= */
void loop() {
  panel.update();
  handleTmButtons();

  loopCounter++;
  unsigned long nowMs = millis();
  if (nowMs - lastLoopHzTime >= 1000UL) {
    loopHz = (unsigned int)loopCounter;
    loopCounter = 0;
    lastLoopHzTime = nowMs;
  }

  ultraLeft.update(nowMs);
  ultraRight.update(nowMs);
  if (!movingByPulses && !emergencyStopActive) ultraSide.update(nowMs);

  if (emergencyStopActive) {
    if (millis() - lastStatusSend >= STATUS_INTERVAL_MS) {
      lastStatusSend = millis();
      sendStatus();
    }
    return;
  }

  // Serial Parser Logic
  if (stringComplete) {
    // If moving by pulses, cleanly discard the complete message
    if (movingByPulses) {
      inputString = "";
      stringComplete = false;
    } else {
      inputString.trim();
      String work = inputString;
      work.toLowerCase();
      
      // Clear for next message
      inputString = "";
      stringComplete = false;

      if (work == "left") {
        panel.setLeft();
      }
      else if (work == "right") {
        panel.setRight();
      }
      else if (work == "stop") {
        queue.clear();
        stopMotor();
        panel.setStop();
      }
      else if (work == "clear" || work == "clear leds" || work == "clearleds") {
        panel.clearPanel();
      }
      else if (work == "allleds" || work == "all leds on") {
        panel.allLedsOn();
      }
      else if (work == "resume") {
        exitForceStop();
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
    }
  }

  int distSide = ultraSide.getCm();
  int dl = ultraLeft.getCm();
  int dr = ultraRight.getCm();
  bool obstacle = (dl > 0 && dl <= STOP_DISTANCE_CM) || (dr > 0 && dr <= STOP_DISTANCE_CM);

  if (lane == 'R' && obstacle) {
    if (!lane_changing_mode) {
      stopMotor();
      queue.clear();
      startServoMoveImmediate(SERVO_CENTER);
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
    startServoMoveImmediate(SERVO_CENTER);
  }

  if (millis() - lastStatusSend >= STATUS_INTERVAL_MS) {
    lastStatusSend = millis();
    sendStatus();
  }

  delay(1);
}

/* =========================
SERIAL EVENT
========================= */
void serialEvent() {
  while (Serial.available()) {
    char c = Serial.read();

    if (emergencyStopActive) {
      continue;
    }

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
  char c = tolower((unsigned char)line.charAt(0));
  return (c == 'f' || c == 'b');
}
