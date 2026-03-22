/*
 * =============================================================
 * Smart Sleep Environment Optimiser — Sensor Data Logger
 * For: Heltec WiFi LoRa 32 V3 (ESP32-S3)
 * =============================================================
 *
 * Data is uploaded to Google Sheets via WiFi every 60 seconds.
 * Also prints to Serial for debugging/monitoring.
 *
 * Sensors:
 *   - DHT11: Temperature & Humidity (GPIO7)
 *   - LDR: Light intensity, analog (GPIO1)
 *   - Microphone: Sound intensity, analog (GPIO2)
 *   - HC-SR501 PIR: Motion detection, digital (GPIO6)
 *   - GY-521 (MPU6050): Accelerometer, I2C (GPIO19/20)
 *
 * Timestamps synced via NTP (internet time).
 * WiFi stays connected to upload data to Google Sheets.
 *
 * =============================================================
 * WIRING SUMMARY
 * =============================================================
 *
 * DHT11:    VCC→3.3V, GND→GND, S→GPIO7
 * LDR:     +→3.3V, −→GND, S→GPIO1
 * Mic:     VCC→5V, GND→GND, AO→GPIO2
 * PIR:     VCC→5V, GND→GND, OUT→GPIO6
 * MPU6050: VCC→3.3V, GND→GND, SDA→GPIO19, SCL→GPIO20
 *
 * =============================================================
 * LIBRARIES TO INSTALL (via Arduino IDE Library Manager):
 *   - DHT sensor library (by Adafruit)
 *   - Wire (built-in)
 *   - WiFi (built-in)
 *   - HTTPClient (built-in)
 *
 * BOARD: "Heltec WiFi LoRa 32(V3) / Wireless shell(V3)"
 * =============================================================
 */

#include <Wire.h>
#include <DHT.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>

// =============================================================
// PIN DEFINITIONS
// =============================================================
#define DHT_PIN       7
#define LDR_PIN       1
#define MIC_PIN       2
#define PIR_PIN       6
#define EXT_SDA       19
#define EXT_SCL       20

// =============================================================
// WIFI & GOOGLE SHEETS CONFIGURATION
// FOR DEPLOYMENT: Update WiFi credentials and Google Apps Script URL
// =============================================================
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Google Apps Script Web App URL
const char* GOOGLE_SCRIPT_URL = "YOUR_SCRIPT_URL";

// NTP (Network Time Protocol) settings
const char* NTP_SERVER = "pool.ntp.org";
const long  GMT_OFFSET_SEC = 0;        // UK = 0 (GMT)
const int   DAYLIGHT_OFFSET_SEC = 0;   // Set to 3600 during BST (summer)

// =============================================================
// CONFIGURATION
// =============================================================
#define SAMPLING_INTERVAL_MS  60000   // 60 seconds between samples
#define DHT_TYPE              DHT11
#define SERIAL_BAUD           115200

// =============================================================
// SENSOR OBJECTS
// =============================================================
DHT dht(DHT_PIN, DHT_TYPE);

#define MPU6050_ADDR 0x68

TwoWire ExtI2C = TwoWire(1);

// =============================================================
// GLOBAL VARIABLES
// =============================================================
unsigned long lastSampleTime = 0;
bool mpuAvailable = false;
bool timeAvailable = false;
int uploadFailCount = 0;

void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(2000);
    
    // Initialise external I2C bus
    ExtI2C.begin(EXT_SDA, EXT_SCL, 100000);
    
    // --- Initialise DHT11 ---
    dht.begin();
    Serial.println("DHT11: Initialised");
    
    // --- Initialise PIR ---
    pinMode(PIR_PIN, INPUT);
    Serial.println("PIR: Initialised");
    
    // --- Connect WiFi ---
    Serial.print("WiFi: Connecting to ");
    Serial.print(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    int wifiAttempts = 0;
    while (WiFi.status() != WL_CONNECTED && wifiAttempts < 30) {
        delay(500);
        Serial.print(".");
        wifiAttempts++;
    }
    
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println(" Connected!");
        Serial.print("WiFi: IP address: ");
        Serial.println(WiFi.localIP());
        
        // Sync time from NTP server
        configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET_SEC, NTP_SERVER);
        
        struct tm timeinfo;
        int ntpAttempts = 0;
        while (!getLocalTime(&timeinfo) && ntpAttempts < 10) {
            delay(500);
            ntpAttempts++;
        }
        
        if (getLocalTime(&timeinfo)) {
            timeAvailable = true;
            Serial.print("NTP: Time synced — ");
            Serial.println(&timeinfo, "%Y-%m-%d %H:%M:%S");
        } else {
            Serial.println("NTP: Failed to sync time — using millis()");
        }
        
        Serial.println("WiFi: Staying connected for Google Sheets uploads");
    } else {
        Serial.println(" Failed to connect!");
        Serial.println("WARNING: No WiFi — data will only be logged to Serial");
    }
    
    // --- Initialise MPU6050 ---
    ExtI2C.begin(EXT_SDA, EXT_SCL, 100000);
    delay(100);
    
    ExtI2C.beginTransmission(MPU6050_ADDR);
    ExtI2C.write(0x6B);
    ExtI2C.write(0x00);
    byte error = ExtI2C.endTransmission();
    
    if (error == 0) {
        mpuAvailable = true;
        
        ExtI2C.beginTransmission(MPU6050_ADDR);
        ExtI2C.write(0x1C);
        ExtI2C.write(0x00);  // ±2G
        ExtI2C.endTransmission();
        
        ExtI2C.beginTransmission(MPU6050_ADDR);
        ExtI2C.write(0x1A);
        ExtI2C.write(0x04);  // ~21Hz filter
        ExtI2C.endTransmission();
        
        Serial.println("MPU6050: Initialised (range: ±2G, filter: 21Hz)");
    } else {
        Serial.println("MPU6050: NOT FOUND — accelerometer data will be -1");
    }
    
    // --- Configure ADC ---
    analogReadResolution(12);
    Serial.println("ADC: 12-bit resolution configured");
    
    // --- Print startup info ---
    Serial.println();
    Serial.println("==============================================");
    Serial.println("  Smart Sleep Environment Optimiser");
    Serial.println("  Sensor Data Logger — Ready");
    Serial.println("==============================================");
    Serial.print("  Sampling interval: ");
    Serial.print(SAMPLING_INTERVAL_MS / 1000);
    Serial.println(" seconds");
    Serial.println("  Upload to: Google Sheets");
    Serial.println("==============================================");
    Serial.println();
    
    // --- Print CSV header (serial only) ---
    Serial.println("timestamp,temp_c,humidity_pct,light_raw,sound_avg,sound_amplitude,pir_triggered,accel_x,accel_y,accel_z,accel_magnitude,upload_status");
    
    // --- Warm-up period ---
    Serial.println("# Warming up sensors (15 seconds)...");
    delay(15000);
    Serial.println("# Warm-up complete. Recording started.");
    Serial.println();
    
    lastSampleTime = millis();
}

void loop() {
    unsigned long currentTime = millis();
    
    if (currentTime - lastSampleTime >= SAMPLING_INTERVAL_MS) {
        lastSampleTime = currentTime;
        takeSample();
    }
    
    // Reconnect WiFi if disconnected
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("WiFi: Connection lost — reconnecting...");
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        int attempts = 0;
        while (WiFi.status() != WL_CONNECTED && attempts < 10) {
            delay(500);
            attempts++;
        }
        if (WiFi.status() == WL_CONNECTED) {
            Serial.println("WiFi: Reconnected!");
        }
    }
}

void takeSample() {
    // --- Timestamp ---
    String timestamp = getTimestamp();
    
    // --- Temperature & Humidity (DHT11) ---
    float temp = dht.readTemperature();
    float humidity = dht.readHumidity();
    if (isnan(temp)) temp = -1;
    if (isnan(humidity)) humidity = -1;
    
    // --- Light (LDR) ---
    int lightRaw = analogRead(LDR_PIN);
    
    // --- Sound (Microphone) ---
    int soundMin = 4095;
    int soundMax = 0;
    int soundReading;
    long soundSum = 0;
    int sampleCount = 0;
    
    unsigned long micStart = millis();
    while (millis() - micStart < 100) {
        soundReading = analogRead(MIC_PIN);
        soundSum += soundReading;
        if (soundReading > soundMax) soundMax = soundReading;
        if (soundReading < soundMin) soundMin = soundReading;
        sampleCount++;
    }
    
    int soundAvg = (sampleCount > 0) ? (soundSum / sampleCount) : 0;
    int soundAmplitude = soundMax - soundMin;
    
    // --- PIR Motion ---
    int pirTriggered = digitalRead(PIR_PIN);
    
    // --- Accelerometer (MPU6050) ---
    float accelX = -1, accelY = -1, accelZ = -1, accelMag = -1;
    
    if (mpuAvailable) {
        ExtI2C.beginTransmission(MPU6050_ADDR);
        ExtI2C.write(0x3B);
        ExtI2C.endTransmission(false);
        ExtI2C.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)6, (uint8_t)true);
        
        if (ExtI2C.available() == 6) {
            int16_t rawX = (ExtI2C.read() << 8) | ExtI2C.read();
            int16_t rawY = (ExtI2C.read() << 8) | ExtI2C.read();
            int16_t rawZ = (ExtI2C.read() << 8) | ExtI2C.read();
            
            accelX = (rawX / 16384.0) * 9.81;
            accelY = (rawY / 16384.0) * 9.81;
            accelZ = (rawZ / 16384.0) * 9.81;
            accelMag = sqrt(accelX * accelX + accelY * accelY + accelZ * accelZ);
        }
    }
    
    // --- Upload to Google Sheets ---
    String uploadStatus = "no_wifi";
    
    if (WiFi.status() == WL_CONNECTED) {
        // Build JSON payload
        String jsonData = "{";
        jsonData += "\"timestamp\":\"" + timestamp + "\",";
        jsonData += "\"temp_c\":" + String(temp, 1) + ",";
        jsonData += "\"humidity_pct\":" + String(humidity, 1) + ",";
        jsonData += "\"light_raw\":" + String(lightRaw) + ",";
        jsonData += "\"sound_avg\":" + String(soundAvg) + ",";
        jsonData += "\"sound_amplitude\":" + String(soundAmplitude) + ",";
        jsonData += "\"pir_triggered\":" + String(pirTriggered) + ",";
        jsonData += "\"accel_x\":" + String(accelX, 3) + ",";
        jsonData += "\"accel_y\":" + String(accelY, 3) + ",";
        jsonData += "\"accel_z\":" + String(accelZ, 3) + ",";
        jsonData += "\"accel_magnitude\":" + String(accelMag, 3);
        jsonData += "}";
        
        HTTPClient http;
        http.begin(GOOGLE_SCRIPT_URL);
        http.addHeader("Content-Type", "application/json");
        http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
        
        int httpResponseCode = http.POST(jsonData);
        
        if (httpResponseCode > 0) {
            uploadStatus = "ok_" + String(httpResponseCode);
            uploadFailCount = 0;
        } else {
            uploadStatus = "fail_" + String(httpResponseCode);
            uploadFailCount++;
        }
        
        http.end();
    } else {
        uploadFailCount++;
    }
    
    // --- Print to Serial (for debugging and backup) ---
    Serial.print(timestamp); Serial.print(",");
    Serial.print(temp, 1); Serial.print(",");
    Serial.print(humidity, 1); Serial.print(",");
    Serial.print(lightRaw); Serial.print(",");
    Serial.print(soundAvg); Serial.print(",");
    Serial.print(soundAmplitude); Serial.print(",");
    Serial.print(pirTriggered); Serial.print(",");
    Serial.print(accelX, 3); Serial.print(",");
    Serial.print(accelY, 3); Serial.print(",");
    Serial.print(accelZ, 3); Serial.print(",");
    Serial.print(accelMag, 3); Serial.print(",");
    Serial.println(uploadStatus);
    
    // Warn if multiple upload failures
    if (uploadFailCount >= 3) {
        Serial.println("WARNING: Multiple upload failures — check WiFi connection");
    }
}

String getTimestamp() {
    if (timeAvailable) {
        struct tm timeinfo;
        if (getLocalTime(&timeinfo)) {
            char buf[20];
            sprintf(buf, "%04d-%02d-%02d %02d:%02d:%02d",
                    timeinfo.tm_year + 1900, timeinfo.tm_mon + 1, timeinfo.tm_mday,
                    timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);
            return String(buf);
        }
    }
    unsigned long ms = millis();
    unsigned long totalSeconds = ms / 1000;
    unsigned long hours = totalSeconds / 3600;
    unsigned long minutes = (totalSeconds % 3600) / 60;
    unsigned long seconds = totalSeconds % 60;
    char buf[12];
    sprintf(buf, "%02lu:%02lu:%02lu", hours, minutes, seconds);
    return String(buf);
}
