# ==================================================
# INSTALL (run once if needed)
# ==================================================
# pip install paho-mqtt pandas scikit-learn matplotlib seaborn

# ==================================================
# IMPORTS
# ==================================================
import json
import time
import os
import pickle
import subprocess
from datetime import datetime

import pandas as pd
import numpy as np

import paho.mqtt.client as mqtt

# ==================================================
# 1. CSV SETUP
# ==================================================
CSV_FILE = "river_data_log.csv"

if not os.path.exists(CSV_FILE):
    df = pd.DataFrame(columns=[
        "timestamp",
        "datetime",
        "water_level_cm",
        "temperature_c",
        "humidity_pct",
        "danger_level",
        "rain_level"
    ])
    df.to_csv(CSV_FILE, index=False)

print("CSV ready:", CSV_FILE)

# ==================================================
# 2. MQTT SETTINGS
# ==================================================
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "river/monitoring/data"

# ==================================================
# 6. GITHUB PUSH FUNCTION
# ==================================================
def push_to_github():
    try:
        # Add the CSV file
        subprocess.run(["git", "add", CSV_FILE], check=True)
        # Commit with a message
        commit_msg = f"Update river data log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        # Push to GitHub
        subprocess.run(["git", "push"], check=True)
        print("Data pushed to GitHub successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Git push failed: {e}")
    except FileNotFoundError:
        print("Git not found. Please ensure Git is installed and the repo is initialized.")

# ==================================================
# 3. MQTT CALLBACK
# ==================================================
def on_message(client, userdata, message, properties=None):
    try:
        data = json.loads(message.payload.decode())

        row = {
            "timestamp": int(data.get("timestamp", time.time() * 1000)),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "water_level_cm": float(data.get("water_level_cm", -1)),
            "temperature_c": float(data.get("temperature_c", -1)),
            "humidity_pct": float(data.get("humidity_pct", -1)),
            "danger_level": int(data.get("danger_level", 0)),
            "rain_level": int(data.get("rain_level", 0))
        }

        pd.DataFrame([row]).to_csv(
            CSV_FILE, mode="a", header=False, index=False
        )

        print("Logged:", row)

    except Exception as e:
        print("MQTT Error:", e)

# ==================================================
# 4. MQTT CLIENT START
# ==================================================
client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT)
client.subscribe(MQTT_TOPIC)
client.loop_start()

print("MQTT running... collecting data")
print("Press CTRL+C to stop and train models\n")

# ==================================================
# 5. RUN MQTT UNTIL STOPPED
# ==================================================
try:
    push_counter = 0
    while True:
        time.sleep(1)
        push_counter += 1
        if push_counter >= 60:  # Every 60 seconds
            push_to_github()
            push_counter = 0

except KeyboardInterrupt:
    print("\nStopping MQTT...\n")
    # Final push before stopping
    push_to_github()
    client.loop_stop()
    client.disconnect()

print("Data collection stopped. You can now run Streamlit for visualization and prediction.")
