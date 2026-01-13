import streamlit as st
import pandas as pd
import numpy as np
import pickle
import time
import logging

# ===========================
# CONFIG
# ===========================
MODEL_FILE = "decision_tree.pkl"  # Dedicated to Decision Tree model
CSV_FILE = "river_data_log.csv"
REFRESH_INTERVAL = 3  # detik
LABELS = ["Aman", "Waspada", "Bahaya"]
STANDARD_WATER_HEIGHT = st.sidebar.number_input("Standard Water Height (cm)", min_value=0.0, max_value=1000.0, value=50.0, step=1.0)

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

# ===========================
# LOGGING
# ===========================
logging.basicConfig(filename="audit_log.txt", level=logging.INFO, format='%(asctime)s %(message)s')

def log_event(event):
    logging.info(event)

# ===========================
# REAL-TIME LOOP
# ===========================
def main():
    # ===========================
    # DATA LOADING & CLEANING
    # ===========================
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
        st.subheader("🤖 Predicted Condition (Decision Tree)")
        
        # Ensure model is loaded and predict
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
        
        # Estimate future prediction horizon
        rise_rate = last["water_rise_rate"]
        current_level = water
        # Assume Bahaya threshold at 35 cm (example, can adjust)
        bahaya_threshold = 35.0
        if rise_rate > 0 and current_level < bahaya_threshold:
            minutes_ahead = ((bahaya_threshold - current_level) / rise_rate) * 60  # convert to minutes
            st.markdown(f"**Prediction Horizon:** Estimated {minutes_ahead:.1f} minutes ahead to potential Bahaya level based on current rise rate.")
        else:
            st.markdown("**Prediction Horizon:** Current trends do not indicate imminent danger, or data insufficient for estimation.")
        
        # Hybrid logic
        if temp_for_pred > 70:
            st.error("ALARM: Suhu ekstrem! Force alarm.")
            log_event("Force alarm due to high temperature.")
        elif pred == "Bahaya" and (confidence is None or confidence > 0.8):
            st.error(f"ALERT: Status Sungai {pred} (confidence: {confidence:.2f})")
            log_event(f"ML ALERT: {pred} (confidence: {confidence})")
        else:
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

if __name__ == "__main__":
    while True:
        main()
        time.sleep(REFRESH_INTERVAL)
        st.rerun()
