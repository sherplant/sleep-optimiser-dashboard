# 🌙 Smart Sleep Environment Optimiser
An IoT system that combines **Garmin wearable** physiological data with a custom **ESP32 bedroom sensor array** to analyse how environmental factors affect sleep quality.
Built as part of an Internet of Things coursework project.
---
## 🔗 Live Dashboard
[View on Streamlit Cloud](https://sleep-optimiser-dashboard-iot.streamlit.app/) 
---
## What It Does
- Tracks sleep stages, heart rate, HRV, stress, body battery and respiration from a Garmin wearable
- Records bedroom temperature, humidity, light and sound levels via a custom ESP32 sensor array
- Uploads sensor data to Google Sheets in real time via WiFi 
- Scores each night using composite sleep and environment quality metrics
- Visualises patterns and correlations across a week of sleep data
- Generates AI-powered sleep insights using a local language model (local only)
---
## Views
| View | Description |
|---|---|
| **Report Cards** | A card for each night — scores, stage breakdown, and click-to-expand detail |
| **Single Night Deep Dive** | Unified timeline of physiology and environment with sleep stage bands overlaid |
| **Sleep Analytics** | Cross-night correlation analysis, scatter plots and environment optimiser |
---
## Running Locally
**Requirements**: Python 3.10+, [Ollama](https://ollama.com) (for AI insights)
```bash
# Install dependencies
pip install -r requirements.txt
# Pull the AI model (optional — only needed for AI insights)
ollama pull llama3.2
# Run the dashboard
python -m streamlit run sleep_dashboard/app.py
```
Then open [http://localhost:8501](http://localhost:8501) in your browser.
> **Note:** The AI Sleep Insights feature requires Ollama running locally. It is automatically disabled in the hosted version.
---
## Data Sources
- **Garmin**: 7 nights of wearable health data (01–07 Mar 2026) exported as CSV from Garmin Connect
- **Arduino**: Bedroom environment readings, including temperature, humidity, light (LDR), sound amplitude, motion, bed movement. Uploaded in real time to Google Sheets via WiFi
---
## Repository Structure
```
├── README.md                 # This file
├── data/
│   ├── loader.py             # Data ingestion
│   ├── processor.py          # Transformation, scoring, alignment
│   └── charts.py             # Reusable Plotly chart components
├── garmin_data/              # Garmin sleep CSVs
├── views/
│   ├── dashboard.py          # Single Night Deep Dive
│   ├── report_card.py        # Report Cards
│   └── explorer.py           # Sleep Analytics
├── .gitignore
├── app.py                    # Entry point and sidebar routing
├── garmin_collect.py         # Garmin Connect API data export script
├── sleep_sensor_logger_iot.ino  # ESP32 Arduino sensor data logger
└── requirements.txt
```
---
## Hardware
- **Microcontroller**: Heltec WiFi LoRa 32 V3 (ESP32-S3)
- **Sensors**: DHT11 (temperature & humidity), LDR (light), large microphone (sound), HC-SR501 PIR (motion), GY-521 MPU6050 (accelerometer)
- **Data pipeline**: Sensors → ESP32 → WiFi → Google Sheets (real-time upload every 60 seconds)
- **Wearable**: Garmin watch → Garmin Connect → Python export script → CSV
---
