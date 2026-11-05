
#include <LiquidCrystal.h>
#include <HX711.h>
#include <SoftwareSerial.h>
#include <TinyGPSPlus.h>
#include <math.h>

// ==========================================
// PIN CONFIGURATION
// ==========================================

// Ultrasonic HC-SR04
#define TRIG_PIN A0
#define ECHO_PIN A1

// Load Cell HX711
#define HX711_SCK A2
#define HX711_DT  A3

// GPS NEO-6M
#define GPS_RX 10
#define GPS_TX 11

// LCD 16x2
LiquidCrystal lcd(7, 6, 5, 4, 3, 2);

// ==========================================
// OBJECTS
// ==========================================

HX711 scale;

SoftwareSerial gpsSerial(GPS_RX, GPS_TX);

TinyGPSPlus gps;

// ==========================================
// CALIBRATION SETTINGS
// ==========================================

// Starting calibration factor.
// Calibrate with a known weight for accuracy.

float calibrationFactor = -2280.0;

// Weight unit: kg
float weightKG = 0.0;

// Ultrasonic distance
float distanceCM = -1.0;

// GPS values
double latitude = 0.0;
double longitude = 0.0;

// Sensor status
bool loadCellReady = false;
bool gpsValid = false;

// ==========================================
// TIMING SETTINGS
// ==========================================

unsigned long lastSensorRead = 0;
unsigned long lastLCDUpdate = 0;
unsigned long lastSerialSend = 0;

const unsigned long SENSOR_INTERVAL = 250;
const unsigned long LCD_INTERVAL = 500;
const unsigned long SERIAL_INTERVAL = 500;

// ==========================================
// HX711 INITIALIZATION
// ==========================================

void initializeLoadCell() {

  scale.begin(HX711_DT, HX711_SCK);

  delay(1000);

  if (scale.wait_ready_timeout(2000)) {

    // Set calibration factor
    scale.set_scale(calibrationFactor);

    // Tare with empty weighing platform
    scale.tare(20);

    loadCellReady = true;

  } else {

    loadCellReady = false;
  }
}

// ==========================================
// SETUP
// ==========================================

void setup() {

  // Serial communication to ESP32
  Serial.begin(9600);

  // GPS initialization
  gpsSerial.begin(9600);

  // Ultrasonic initialization
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  digitalWrite(TRIG_PIN, LOW);

  // LCD initialization
  lcd.begin(16, 2);
  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("CARGONEST SYSTEM");

  lcd.setCursor(0, 1);
  lcd.print("INITIALIZING...");

  // HX711 initialization
  initializeLoadCell();

  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("SENSOR STATUS");

  lcd.setCursor(0, 1);

  if (loadCellReady) {

    lcd.print("HX711 READY");

  } else {

    lcd.print("HX711 ERROR");
  }

  delay(1500);

  lcd.clear();
}

// ==========================================
// ULTRASONIC SENSOR
// ==========================================

void readUltrasonic() {

  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);

  digitalWrite(TRIG_PIN, LOW);

  unsigned long duration =
      pulseIn(ECHO_PIN, HIGH, 30000UL);

  if (duration == 0) {

    distanceCM = -1.0;

  } else {

    distanceCM =
        (duration * 0.0343) / 2.0;
  }
}

// ==========================================
// HX711 LOAD CELL MEASUREMENT
// ==========================================

void readLoadCell() {

  if (!scale.wait_ready_timeout(500)) {

    loadCellReady = false;
    weightKG = -1.0;

    return;
  }

  // Read average of 5 measurements
  float measuredWeight = scale.get_units(5);

  if (!isfinite(measuredWeight)) {

    loadCellReady = false;
    weightKG = -1.0;

    return;
  }

  loadCellReady = true;

  weightKG = measuredWeight;

  // Remove small fluctuations around zero
  if (weightKG > -0.02 && weightKG < 0.02) {

    weightKG = 0.0;
  }
}

// ==========================================
// GPS READING
// ==========================================

void readGPS() {

  while (gpsSerial.available() > 0) {

    gps.encode(gpsSerial.read());
  }

  if (gps.location.isValid() &&
      gps.location.age() < 5000) {

    latitude = gps.location.lat();

    longitude = gps.location.lng();

    gpsValid = true;

  } else {

    gpsValid = false;
  }
}

// ==========================================
// LCD DISPLAY
// ==========================================

void updateLCD() {

  // ROW 1: Distance and GPS status
  lcd.setCursor(0, 0);

  if (distanceCM >= 0) {

    lcd.print("D:");
    lcd.print(distanceCM, 1);
    lcd.print("cm ");

  } else {

    lcd.print("D:---cm ");
  }

  lcd.print(gpsValid ? "GPS+" : "GPS-");

  // Clear remaining characters
  lcd.print(" ");

  // ROW 2: Load cell weight
  lcd.setCursor(0, 1);

  if (loadCellReady) {

    lcd.print("W:");
    lcd.print(weightKG, 2);
    lcd.print(" kg");

  } else {

    lcd.print("W:HX711 ERROR");
  }

  lcd.print("    ");
}

// ==========================================
// SEND DATA TO ESP32
// ==========================================

void sendDataToESP32() {

  // Data format:
  // DATA,DISTANCE,WEIGHT,LATITUDE,LONGITUDE,GPS

  Serial.print("DATA,");

  Serial.print(distanceCM, 2);
  Serial.print(",");

  if (loadCellReady) {

    Serial.print(weightKG, 3);

  } else {

    Serial.print(-1.0, 3);
  }

  Serial.print(",");

  Serial.print(latitude, 6);
  Serial.print(",");

  Serial.print(longitude, 6);
  Serial.print(",");

  Serial.println(gpsValid ? 1 : 0);
}

// ==========================================
// MAIN LOOP
// ==========================================

void loop() {

  unsigned long currentTime = millis();

  // Continuously process GPS
  readGPS();

  // Read sensors
  if (currentTime - lastSensorRead >= SENSOR_INTERVAL) {

    lastSensorRead = currentTime;

    readUltrasonic();

    readLoadCell();
  }

  // LCD update
  if (currentTime - lastLCDUpdate >= LCD_INTERVAL) {

    lastLCDUpdate = currentTime;

    updateLCD();
  }

  // Transmit sensor data to ESP32
  if (currentTime - lastSerialSend >= SERIAL_INTERVAL) {

    lastSerialSend = currentTime;

    sendDataToESP32();
  }
}
