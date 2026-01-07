# ==================================================
# RETRAIN MODEL SCRIPT
# ==================================================
import pandas as pd
import numpy as np
import pickle
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# ==================================================
# CONFIG
# ==================================================
CSV_FILE = "river_data_log.csv"
MODEL_FILE = "decision_tree.pkl"
STANDARD_WATER_HEIGHT = 50.0  # Default, can be adjusted
LABELS = ["Aman", "Waspada", "Bahaya"]

# ==================================================
# LOAD AND PREPROCESS DATA
# ==================================================
def load_and_preprocess_data():
    df = pd.read_csv(CSV_FILE)
    df = df.sort_values("timestamp")
    # Range check & noise filter
    df = df[(df["water_level_cm"].between(0, 1000)) &
            (df["temperature_c"].between(-10, 80)) &
            (df["humidity_pct"].between(0, 100))]
    df = df.dropna()  # Drop missing for training
    # Map danger_level to labels
    df["danger_label"] = df["danger_level"].map({i: label for i, label in enumerate(LABELS)})
    df = df.dropna(subset=["danger_label"])  # Drop invalid labels
    # Normalization
    df["water_level_norm"] = df["water_level_cm"] / STANDARD_WATER_HEIGHT
    # Water rise rate
    df["water_rise_rate"] = df["water_level_cm"].diff().fillna(0)
    # Rain binary
    df["rain"] = (df["rain_level"] > 0).astype(int)
    return df

# ==================================================
# RETRAIN MODEL
# ==================================================
def retrain_model():
    df = load_and_preprocess_data()
    if len(df) < 10:  # Minimum data for training
        print("Not enough data for retraining.")
        return False

    features = ["water_level_norm", "water_rise_rate", "rain", "humidity_pct"]
    target = "danger_label"

    X = df[features]
    y = df[target]

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Train Decision Tree
    model = DecisionTreeClassifier(random_state=42)
    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"Model retrained with accuracy: {accuracy:.2f}")

    # Save model
    with open(MODEL_FILE, "wb") as f:
        pickle.dump(model, f)

    print("Model saved to", MODEL_FILE)
    return True

if __name__ == "__main__":
    retrain_model()