// ESP32-AI-Thinker CAM -> MQTT alert subscriber -> sends photo to Telegram
// Features:
// - Conservative camera settings to reduce memory use
// - Option to verify Telegram TLS via root CA (paste PEM into TELEGRAM_ROOT_CA)
// - Multipart upload to Telegram API
// - Fallback: publish base64 image to MQTT topic for gateway to forward

#include "WiFi.h"
#include "PubSubClient.h"
#include "esp_camera.h"
#include "WiFiClientSecure.h"
#include "base64.h"

// --------- CONFIG - fill these ---------
const char* ssid = "Merti Desa";
const char* password = "";
const char* mqtt_server = "broker.hivemq.com";
const int mqtt_port = 1883;
const char* alert_topic = "river/alert/cam";
const char* image_mqtt_topic = "river/alert/image"; // optional fallback: base64 image

// Telegram (fill these)
const char* TELEGRAM_BOT_TOKEN = "8461118981:AAEhYY4SmJjhRtEQoWVCDkCz7MCZ8prRejU"; // e.g. 123456:ABC-DEF
const char* TELEGRAM_CHAT_ID = "1974714508";   // e.g. 987654321

// If you have the API root CA PEM, paste it here (recommended for production).
// Leave empty to use insecure TLS for quick testing.
const char* TELEGRAM_ROOT_CA = "";

WiFiClientSecure secureClient;
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

// AI Thinker camera pins (standard)
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM       5

#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// Camera configuration helper
void setup_camera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // Use conservative size to avoid memory issues; adjust as needed
  config.frame_size = FRAMESIZE_VGA; // smaller -> lower memory and faster upload
  config.jpeg_quality = 12; // 10-15 is a good compromise
  config.fb_count = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
  } else {
    Serial.println("Camera initialized");
  }
}

// Send photo to Telegram via HTTPS multipart/form-data. Tries CA verify if provided.
bool sendPhotoToTelegram(camera_fb_t * fb) {
  if (!fb) return false;

  String host = "api.telegram.org";
  String path = "/bot" + String(TELEGRAM_BOT_TOKEN) + "/sendPhoto";

  String boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW";
  String head = "--" + boundary + "\r\n";
  head += "Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n" + String(TELEGRAM_CHAT_ID) + "\r\n";
  head += "--" + boundary + "\r\n";
  head += "Content-Disposition: form-data; name=\"photo\"; filename=\"image.jpg\"\r\n";
  head += "Content-Type: image/jpeg\r\n\r\n";
  String tail = "\r\n--" + boundary + "--\r\n";

  // Set CA or fallback to insecure (only for testing)
  if (TELEGRAM_ROOT_CA && strlen(TELEGRAM_ROOT_CA) > 10) {
    secureClient.setCACert(TELEGRAM_ROOT_CA);
  } else {
    secureClient.setInsecure();
    Serial.println("Warning: TLS verification disabled. Set TELEGRAM_ROOT_CA for production.");
  }

  if (!secureClient.connect(host.c_str(), 443)) {
    Serial.println("Failed to connect to Telegram");
    return false;
  }

  String contentType = "multipart/form-data; boundary=" + boundary;
  size_t contentLength = head.length() + fb->len + tail.length();

  String req = String("POST ") + path + " HTTP/1.1\r\n";
  req += "Host: " + host + "\r\n";
  req += "Content-Type: " + contentType + "\r\n";
  req += "Connection: close\r\n";
  req += "Content-Length: " + String(contentLength) + "\r\n\r\n";

  secureClient.print(req);
  secureClient.print(head);

  // send image binary
  secureClient.write(fb->buf, fb->len);
  secureClient.print(tail);

  unsigned long timeout = millis() + 7000;
  bool ok = false;
  while (secureClient.connected() && millis() < timeout) {
    while (secureClient.available()) {
      String line = secureClient.readStringUntil('\n');
      // debug print
      Serial.println(line);
      if (line.indexOf("\"ok\":true") >= 0) ok = true;
      timeout = millis() + 7000;
    }
  }

  secureClient.stop();
  return ok;
}

// Fallback: publish base64 image over MQTT for a gateway to forward (optional)
bool publishImageOverMQTT(camera_fb_t * fb) {
  if (!mqttClient.connected()) return false;
  String b64 = base64::encode(fb->buf, fb->len);
  // WARNING: large payloads may fail depending on broker; consider chunking
  bool ok = mqttClient.publish(image_mqtt_topic, b64.c_str());
  Serial.printf("Published image over MQTT: %s\n", ok ? "OK" : "FAIL");
  return ok;
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  Serial.printf("MQTT message arrived [%s]: %s\n", topic, msg.c_str());
  if (String(topic) == String(alert_topic) && msg == "CAPTURE") {
    Serial.println("Capture command received — taking photo...");
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      return;
    }

    bool sent = sendPhotoToTelegram(fb);
    if (!sent) {
      Serial.println("Telegram upload failed — publishing image to MQTT as fallback");
      publishImageOverMQTT(fb);
    } else {
      Serial.println("Telegram upload OK");
    }

    esp_camera_fb_return(fb);
  }
}

void reconnectMqtt() {
  while (!mqttClient.connected()) {
    Serial.print("Connecting MQTT...");
    if (mqttClient.connect("ESP32_CAM_CLIENT")) {
      Serial.println("connected");
      mqttClient.subscribe(alert_topic);
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" try again in 2 seconds");
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print('.');
    delay(500);
  }
  Serial.println("\nWiFi connected");

  setup_camera();

  mqttClient.setServer(mqtt_server, mqtt_port);
  mqttClient.setCallback(mqttCallback);
}

void loop() {
  if (!mqttClient.connected()) reconnectMqtt();
  mqttClient.loop();
  delay(10);
}
