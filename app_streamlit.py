import streamlit as st
import pandas as pd
import pickle
import time
import threading
import json
import os
from paho.mqtt import client as mqtt

# ===========================
# CONFIG
# ===========================
MODEL_PATH = "decision_tree.pkl"
CSV_PATH = "river_data_log.csv"

# ===========================
# HELPERS
# ===========================
def normalize_emoji(label):
    l = label.upper()
    return {
        "AMAN": "🟢",
        "WASPADA": "🟡",
        "BAHAYA": "🔴"
    }.get(l, "❓")

def status_box(title, level, mode="danger"):
    if mode == "danger":
        if level == 0: color="#4fc3f7"; emoji="🟢"; text="SAFE"
        elif level == 1: color="#29b6f6"; emoji="🟡"; text="WARNING"
        else: color="#0277bd"; emoji="🔴"; text="DANGEROUS"
    elif mode == "rain":
        if level == 0: color="#4fc3f7"; emoji="🌤️"; text="NO RAIN"
        elif level == 1: color="#29b6f6"; emoji="🌦️"; text="LIGHT RAIN"
        else: color="#0277bd"; emoji="🌧️"; text="HEAVY RAIN"

    st.markdown(f"""
        <div style="padding:20px; border-radius:15px; background:{color}; text-align:center;">
            <h2 style="color:white;">{title}</h2>
            <h1 style="color:white; font-size:50px;">{emoji}</h1>
            <h3 style="color:white;">{text}</h3>
        </div>
    """, unsafe_allow_html=True)
with open(MODEL_PATH, "rb") as f:
    model = pickle.load(f)

# ===========================
# INIT CSV IF NOT EXISTS
# ===========================
if not os.path.exists(CSV_PATH):
    df0 = pd.DataFrame(columns=[
        "timestamp",
        "water_level_cm",
        "rain_level",
        "danger_level",
        "humidity_pct",
        "temperature_c",
        "datetime"
    ])
    df0.to_csv(CSV_PATH, index=False)

# ===========================
# GLOBAL VARIABLE
# ===========================
latest_mqtt = None
mqtt_lock = threading.Lock()

# ===========================
# MQTT CALLBACK
# ===========================
def on_message(client, userdata, msg):
    global latest_mqtt

    try:
        payload = msg.payload.decode()

        try:
            raw = json.loads(payload)
            data = {
                "timestamp": raw.get("timestamp", None),
                "water_level_cm": float(raw.get("water_level_cm", 0)),
                "rain_level": int(raw.get("rain_level", 0)),
                "danger_level": int(raw.get("danger_level", 0)),
                "humidity_pct": float(raw.get("humidity_pct", 0)),
                "temperature_c": float(raw.get("temperature_c", 0)),
            }

        except:
            # fallback CSV-like "water,rain,danger,hum"
            parts = payload.split(",")
            data = {
                "timestamp": None,
                "water_level_cm": float(parts[0]),
                "rain_level": int(parts[1]),
                "danger_level": int(parts[2]),
                "humidity_pct": float(parts[3]),
                "temperature_c": None
            }

        with mqtt_lock:
            latest_mqtt = data

    except Exception as e:
        print("MQTT error:", e)


def mqtt_thread():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe(MQTT_TOPIC)
    client.loop_forever()


# START BACKGROUND MQTT LISTENER
mqtt_bg = threading.Thread(target=mqtt_thread, daemon=True)
mqtt_bg.start()

# ===========================
# STREAMLIT SETTINGS
# ===========================
st.set_page_config(page_title="River Monitor + MQTT + ML", layout="wide")
st.title("🌊 River Monitoring Dashboard — Real-Time + Prediction")

# Blue-ish background
st.markdown("""
<style>
body {
    background-color: #e0f7fa;
}
</style>
""", unsafe_allow_html=True)

# ========== SIDEBAR ==========
st.sidebar.title("Pengaturan")
refresh = st.sidebar.button("Refresh Sekarang")

# Manual Override Section
st.sidebar.subheader("Manual Override")
manual_water_level = st.sidebar.number_input("Manual Water Level (cm)", min_value=0.0, max_value=1000.0, value=None, step=1.0, help="Leave empty to use sensor data")
manual_temp = st.sidebar.number_input("Manual Temperature (°C)", min_value=-10.0, max_value=80.0, value=None, step=0.1, help="Leave empty to use sensor data")
manual_humidity = st.sidebar.number_input("Manual Humidity (%)", min_value=0.0, max_value=100.0, value=None, step=0.1, help="Leave empty to use sensor data")
manual_rain = st.sidebar.selectbox("Manual Rain", [None, 0, 1], help="0=No Rain, 1=Rain, None=Use sensor")
manual_danger = st.sidebar.selectbox("Manual Danger Level Override", [None, "Aman", "Waspada", "Bahaya"], help="Override the predicted danger level")
submit_manual = st.sidebar.button("Submit Manual Override")

# ========== MAIN ==========
df = load_data()

if refresh:
    st.cache_data.clear()
    df = load_data()
    log_event("Data refreshed manually")

log_event(f"Dashboard accessed, data points: {len(df)}")

if df.empty:
    st.info("Waiting for data...")
    st.stop()

# 2. Use last row
last = df.iloc[-1]

water = last["water_level_cm"]
rain = last["rain"]
danger = last["danger_level"] if "danger_level" in df.columns else 0
hum = last["humidity_pct"]

# ===========================
# DISPLAY UI
# ===========================
col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Water Level (cm)", water)
with col2:
    status_box("Danger Level", int(danger), mode="danger")
with col3:
    status_box("Rain Level", int(rain), mode="rain")

st.subheader("📈 Water Level Over Time")
st.line_chart(df["water_level_cm"])

# ========== PREDICTION ==========
fitur = ["water_level_norm", "water_rise_rate", "rain", "humidity_pct"]
model = load_model()

if model is not None and not df.empty:
    latest = df[fitur].tail(1).copy()
    
    # Apply manual overrides if submitted
    if submit_manual:
        if manual_water_level is not None:
            latest["water_level_norm"] = manual_water_level / STANDARD_WATER_HEIGHT
            latest["water_rise_rate"] = manual_water_level - df["water_level_cm"].iloc[-2] if len(df) > 1 else 0
        if manual_rain is not None:
            latest["rain"] = manual_rain
        if manual_humidity is not None:
            latest["humidity_pct"] = manual_humidity
        temp_for_pred = manual_temp if manual_temp is not None else df["temperature_c"].iloc[-1]
        if manual_danger is not None:
            pred = manual_danger
            confidence = None
            st.info("Manual override applied.")
        else:
            # Normal prediction
            confidence = None
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(latest)
                confidence = np.max(proba)
                pred = model.predict(latest)[0]
            else:
                pred = model.predict(latest)[0]
                confidence = None
            temp_for_pred = df["temperature_c"].iloc[-1]
    else:
        # Normal prediction without manual override
        confidence = None
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(latest)
            confidence = np.max(proba)
            pred = model.predict(latest)[0]
        else:
            pred = model.predict(latest)[0]
            confidence = None
        temp_for_pred = df["temperature_c"].iloc[-1]
    
    # Hybrid logic
    if temp_for_pred > 70:
        st.error("ALARM: Suhu ekstrem! Force alarm.")
        log_event("Force alarm due to high temperature.")
    elif pred == "Bahaya" and (confidence is None or confidence > 0.8):
        st.error(f"ALERT: Status Sungai {pred} (confidence: {confidence:.2f})")
        log_event(f"ML ALERT: {pred} (confidence: {confidence})")
    else:
        st.subheader("🤖 Predicted Condition (Decision Tree)")
        label = pred
        emoji = normalize_emoji(label)

        st.markdown(f"""
            <div style="padding:25px; border-radius:15px; background:#0277bd; color:white; text-align:center;">
                <h2>Prediction:</h2>
                <h1 style="font-size:60px;">{emoji}</h1>
                <h1>{label}</h1>
                {f"<p>Confidence: {confidence:.2f}</p>" if confidence else ""}
            </div>
        """, unsafe_allow_html=True)
        log_event(f"Prediction: {pred} (confidence: {confidence})")
else:
    st.warning("Model belum tersedia atau data kosong.")

# ========== VISUALIZATION ==========
st.subheader("📈 Water Level Over Time")
st.line_chart(df.set_index("timestamp")["water_level_cm"])

st.info("Training model dilakukan manual/terjadwal. Data waktu tidak digunakan sebagai fitur input model.")
