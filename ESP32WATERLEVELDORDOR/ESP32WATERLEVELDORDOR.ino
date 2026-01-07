#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>

// ================================
// WIFI CONFIG
// ================================
const char* ssid = "Merti Desa";
const char* password = "";

// ================================
// MQTT CONFIG
// ================================
const char* mqtt_server = "broker.hivemq.com";
const int mqtt_port = 1883;

const char* data_topic  = "river/monitoring/data";
const char* alert_topic = "river/alert/cam";

WiFiClient espClient;
PubSubClient client(espClient);

// ================================
// SENSOR PINS
// ================================
#define TRIG_PIN 5
#define ECHO_PIN 18
#define DHT_PIN 14
#define DHTTYPE DHT11
DHT dht(DHT_PIN, DHTTYPE);

// RainDrop HW-028 AO pin
#define RAIN_PIN 34    // analog ADC pin

// ================================
// SAFE PARAMETER (ADJUSTABLE)
// ================================
float safeParameter = 50.0;   // cm baseline distance

// ================================
// VARIABLES
// ================================
float lastLevel = -1;
unsigned long lastCheck = 0;
unsigned long hourlyTimer = 60000;
unsigned long interval = 5000;
unsigned long lastSend = 0;

// alert debounce
unsigned long lastAlertTime = 0;
unsigned long alertInterval = 5 * 60 * 1000UL; // 5 minutes between alerts

float dangerRiseMin = 15.0;

// -----------------------------------------------------
// READ ULTRASONIC
// -----------------------------------------------------
float readUltrasonic() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH);
  float distance = duration * 0.034 / 2;
  return distance;
}

// -----------------------------------------------------
// READ RAIN SENSOR (HW-028)
// -----------------------------------------------------
int readRainLevel() {
  int rainValue = analogRead(RAIN_PIN);  
  // ESP32 ADC range = 0–4095

  // Sensor behavior:
  // 4095 = dry
  // <3000 = drizzle
  // <2000 = moderate rain
  // <1000 = heavy rain

  int rainLevel = 0;

  if (rainValue < 3000 && rainValue >= 2000) {
    rainLevel = 1;        // drizzle
  } 
  else if (rainValue < 2000 && rainValue >= 1000) {
    rainLevel = 2;        // moderate rain
  } 
  else if (rainValue < 1000) {
    rainLevel = 3;        // heavy rain
  }

  return rainLevel;
}

// -----------------------------------------------------
// MQTT RECONNECT
// -----------------------------------------------------
void reconnectMQTT() {
  while (!client.connected()) {
    Serial.print("Connecting MQTT...");
    if (client.connect("ESP32_RiverMain")) {
      Serial.println("Connected.");
    } else {
      Serial.println("Retry...");
      delay(1500);
    }
  }
}

// -----------------------------------------------------
// SETUP
// -----------------------------------------------------
void setup() {
  Serial.begin(115200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  dht.begin();

  WiFi.begin(ssid, password);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(400);
  }
  Serial.println("\nWiFi connected!");

  client.setServer(mqtt_server, mqtt_port);
}

// -----------------------------------------------------
// LOOP
// -----------------------------------------------------
void loop() {
  if (!client.connected()) reconnectMQTT();
  client.loop();

  unsigned long now = millis();

  // ======================
  // SEND DATA EVERY 5s
  // ======================
  if (now - lastSend >= interval) {
    lastSend = now;

    float level = readUltrasonic();
    float temp  = dht.readTemperature();
    float hum   = dht.readHumidity();
    int rainLevel = readRainLevel();

    // ------ WATER LEVEL → DANGER LEVEL ------
    float riseAmount = safeParameter - level;
    int dangerLevel = 0;

    if (riseAmount > 5 && riseAmount <= 10) dangerLevel = 1;
    else if (riseAmount > 10 && riseAmount <= 20) dangerLevel = 2;
    else if (riseAmount > 20) dangerLevel = 3;

    // ------ JSON ------
    String payload = "{";
    payload += "\"timestamp\":" + String(now) + ",";
    payload += "\"water_level_cm\":" + String(level, 2) + ",";
    payload += "\"temperature_c\":" + String(temp, 2) + ",";
    payload += "\"humidity_pct\":" + String(hum, 2) + ",";
    payload += "\"danger_level\":" + String(dangerLevel) + ",";
    payload += "\"rain_level\":" + String(rainLevel);
    payload += "}";

    client.publish(data_topic, payload.c_str());
    Serial.println("MQTT Sent: " + payload);

    // Immediate alert when dangerLevel >= 2 (Waspada/Bahaya)
    if (dangerLevel >= 2) {
      if (now - lastAlertTime >= alertInterval) {
        Serial.println("Danger level high — requesting camera capture");
        client.publish(alert_topic, "CAPTURE");
        lastAlertTime = now;
      } else {
        Serial.println("Alert suppressed to avoid spamming camera.");
      }
    }
  }

  // ======================
  // HOURLY CHECK
  // ======================
  if (now - lastCheck >= hourlyTimer) {
    float currentLevel = readUltrasonic();

    if (lastLevel < 0) {
      lastLevel = currentLevel;
      lastCheck = now;
      return;
    }

    float rise = lastLevel - currentLevel;

    lastLevel = currentLevel;
    lastCheck = now;

    Serial.print("Hourly rise = ");
    Serial.println(rise);

    if (rise > dangerRiseMin) {
      Serial.println("!!! DANGER RISE — CAPTURE !!!");
      client.publish(alert_topic, "CAPTURE");
    }
  }
}