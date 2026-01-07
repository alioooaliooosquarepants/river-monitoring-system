import streamlit as st
import pandas as pd
import numpy as np
import pickle
import time
import logging

# ========== CONFIGURABLES ==========
CSV_FILE = "river_data_log.csv"
MODEL_FILE = "decision_tree.pkl"  # Dedicated to Decision Tree model
REFRESH_INTERVAL = 3  # detik
LABELS = ["Aman", "Waspada", "Bahaya"]
STANDARD_WATER_HEIGHT = st.sidebar.number_input("Standard Water Height (cm)", min_value=0.0, max_value=1000.0, value=50.0, step=1.0)

# ========== LOGGING ==========
logging.basicConfig(filename="audit_log.txt", level=logging.INFO, format='%(asctime)s %(message)s')

def log_event(event):
    logging.info(event)

# ========== DATA LOADING & CLEANING ==========
@st.cache_data(ttl=REFRESH_INTERVAL)
def load_data():
    df = pd.read_csv(CSV_FILE)
    df = df.sort_values("timestamp")
    # Range check & noise filter
    df = df[(df["water_level_cm"].between(0, 1000)) &
            (df["temperature_c"].between(-10, 80)) &
            (df["humidity_pct"].between(0, 100))]
    df = df.fillna(method="ffill").fillna(method="bfill")  # handle missing data
    # Normalization
    df["water_level_norm"] = df["water_level_cm"] / STANDARD_WATER_HEIGHT
    # Water rise rate
    df["water_rise_rate"] = df["water_level_cm"].diff().fillna(0)
    # Rain binary
    df["rain"] = (df["rain_level"] > 0).astype(int)
    return df

@st.cache_resource
def load_model():
    try:
        model = pickle.load(open(MODEL_FILE, "rb"))
        return model
    except Exception:
        return None

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
st.title("Visualisasi & Prediksi Ketinggian Air Sungai")
df = load_data()

if refresh:
    st.cache_data.clear()
    df = load_data()

st.write(f"Data terbaru (auto-refresh {REFRESH_INTERVAL} detik):")
st.dataframe(df.tail(10))

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
        st.subheader("Prediksi Status Sungai:")
        st.write(f"**{pred}**" + (f" (confidence: {confidence:.2f})" if confidence else ""))
        log_event(f"Prediction: {pred} (confidence: {confidence})")
else:
    st.warning("Model belum tersedia atau data kosong.")

# ========== VISUALIZATION ==========
st.subheader("Grafik Ketinggian Air")
st.line_chart(df.set_index("timestamp")["water_level_cm"])

st.subheader("Grafik Laju Kenaikan Air")
st.line_chart(df.set_index("timestamp")["water_rise_rate"])

st.subheader("Grafik Kelembapan")
st.line_chart(df.set_index("timestamp")["humidity_pct"])

st.subheader("Grafik Hujan (Biner)")
st.line_chart(df.set_index("timestamp")["rain"])

st.info("Training model dilakukan manual/terjadwal. Data waktu tidak digunakan sebagai fitur input model.")
