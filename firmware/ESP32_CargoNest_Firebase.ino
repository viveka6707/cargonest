
#include <WiFi.h>
#include <Firebase_ESP_Client.h>

// ---------------- WIFI SETTINGS ----------------

#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"

// ---------------- FIREBASE SETTINGS ----------------
#define API_KEY         "YOUR_FIREBASE_WEB_API_KEY"
#define DATABASE_URL    "https://projectbase2027-acee2-default-rtdb.firebaseio.com/"
#define DATABASE_PATH "/CargoNest/data"

// ---------------- NANO SERIAL ----------------

#define NANO_RX 16
#define NANO_TX 17

HardwareSerial NanoSerial(2);

// ---------------- FIREBASE OBJECTS ----------------

FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig config;

// ---------------- SENSOR VARIABLES ----------------

float distanceCM = -1.0;
float weightKG = -1.0;

double latitude = 0.0;
double longitude = 0.0;

bool gpsValid = false;

bool nanoConnected = false;
bool firebaseReady = false;

unsigned long lastNanoData = 0;
unsigned long lastFirebaseUpload = 0;

const unsigned long NANO_TIMEOUT = 5000;
const unsigned long UPLOAD_INTERVAL = 2000;

// ---------------- SERIAL BUFFER ----------------

char serialBuffer[120];
int serialIndex = 0;

// ---------------- WIFI CONNECTION ----------------

void connectWiFi() {

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");

  while (WiFi.status() != WL_CONNECTED) {

    Serial.print(".");
    delay(500);
  }

  Serial.println();
  Serial.println("WiFi Connected");

  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
}

// ---------------- FIREBASE CONNECTION ----------------

void connectFirebase() {

  config.api_key = API_KEY;
  config.database_url = DATABASE_URL;

  Serial.println("Firebase Authentication...");

  if (Firebase.signUp(&config, &auth, "", "")) {

    Serial.println("Firebase Authentication Successful");

  } else {

    Serial.print("Firebase Signup Error: ");

    Serial.println(
      config.signer.signupError.message.c_str()
    );

    return;
  }

  Firebase.begin(&config, &auth);

  Firebase.reconnectWiFi(true);

  firebaseReady = true;

  Serial.println("Firebase Connected");
}

// ---------------- SETUP ----------------

void setup() {

  Serial.begin(115200);

  // Arduino Nano communication
  NanoSerial.begin(
    9600,
    SERIAL_8N1,
    NANO_RX,
    NANO_TX
  );

  Serial.println();
  Serial.println("================================");
  Serial.println(" ESP32 SENSOR DATA RECEIVER");
  Serial.println("================================");

  connectWiFi();

  connectFirebase();
}

// ---------------- RECEIVE NANO DATA ----------------


void receiveNanoData() {

  while (NanoSerial.available() > 0) {

    char ch = NanoSerial.read();

    if (ch == '\n') {

      serialBuffer[serialIndex] = '\0';

      Serial.print("RAW NANO DATA: ");
      Serial.println(serialBuffer);

      processSensorData(serialBuffer);

      serialIndex = 0;
    }

    else if (ch != '\r') {

      if (serialIndex < sizeof(serialBuffer) - 1) {

        serialBuffer[serialIndex++] = ch;

      } else {

        Serial.println("Serial buffer overflow");
        serialIndex = 0;
      }
    }
  }
}


// ---------------- PROCESS SENSOR DATA ----------------

void processSensorData(char *data) {

  char buffer[120];

  strncpy(buffer, data, sizeof(buffer) - 1);
  buffer[sizeof(buffer) - 1] = '\0';

  char *header = strtok(buffer, ",");

  if (header == NULL || strcmp(header, "DATA") != 0) {
    return;
  }

  char *distance = strtok(NULL, ",");
  char *weight = strtok(NULL, ",");
  char *lat = strtok(NULL, ",");
  char *lng = strtok(NULL, ",");
  char *gps = strtok(NULL, ",");

  if (!distance || !weight || !lat ||
      !lng || !gps) {
    Serial.println("Invalid serial packet");
    return;
  }

  float d = atof(distance);
  float w = atof(weight);

  double la = atof(lat);
  double lo = atof(lng);

  int g = atoi(gps);

  if (!isfinite(d) || !isfinite(w) ||
      !isfinite(la) || !isfinite(lo) ||
      (g != 0 && g != 1)) {

    Serial.println("Invalid sensor values");
    return;
  }

  distanceCM = d;
  weightKG = w;

  latitude = la;
  longitude = lo;

  gpsValid = (g == 1);

  lastNanoData = millis();

  nanoConnected = true;

  // -------- SERIAL MONITOR --------

  Serial.println();
  Serial.println("------ RECEIVED DATA ------");

  Serial.print("Distance : ");
  Serial.print(distanceCM);
  Serial.println(" cm");

  Serial.print("Weight   : ");
  Serial.print(weightKG);
  Serial.println(" kg");

  Serial.print("Latitude : ");
  Serial.println(latitude, 6);

  Serial.print("Longitude: ");
  Serial.println(longitude, 6);

  Serial.print("GPS      : ");
  Serial.println(gpsValid ? "VALID" : "NO FIX");

  Serial.println("---------------------------");
}

// ---------------- FIREBASE UPLOAD ----------------

void uploadFirebaseData() {

  if (!Firebase.ready()) {
    Serial.println("Firebase not ready");
    return;
  }

  FirebaseJson json;
  json.set("distance_cm", distanceCM);
  json.set("weight_kg", weightKG);
  json.set("latitude", latitude);
  json.set("longitude", longitude);
  json.set("gps_valid", gpsValid);
  json.set("nano_connected", nanoConnected);

  json.set("updated_ms", (double)millis());

  if (Firebase.RTDB.updateNode(
        &fbdo,
        DATABASE_PATH,
        &json)) {
    Serial.println("Firebase Upload Successful");
  } else {
    Serial.print("Firebase Upload Failed: ");
    Serial.println(fbdo.errorReason());
  }
}

// ---------------- MAIN LOOP ----------------

void loop() {

  unsigned long now = millis();
  // Receive Arduino Nano data
  receiveNanoData();
  // Check Nano communication
  if (lastNanoData > 0 &&
      now - lastNanoData > NANO_TIMEOUT) {
    nanoConnected = false;
    gpsValid = false;
    distanceCM = -1.0;
    weightKG = -1.0;
  }

  // WiFi reconnection
  if (WiFi.status() != WL_CONNECTED) {
    firebaseReady = false;
    Serial.println("WiFi disconnected. Reconnecting...");
    WiFi.reconnect();
    delay(100);
    return;
  }

  // Firebase reconnection
  if (!firebaseReady) {
    connectFirebase();
    delay(100);
    return;
  }

  // Upload every 2 seconds
  if (now - lastFirebaseUpload >= UPLOAD_INTERVAL) {
    lastFirebaseUpload = now;
    uploadFirebaseData();
  }
}
