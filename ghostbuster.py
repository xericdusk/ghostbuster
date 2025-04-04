import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import datetime
import openai
import base64
import os
import subprocess
import json

# --------- SETTINGS ---------
LOG_DIR = "logs"
IQ_DIR = "iq_recordings"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(IQ_DIR, exist_ok=True)

# OpenAI client setup
from openai import OpenAI
client = OpenAI(api_key=st.secrets["openai_api_key"])

# --------- UI SETUP ---------
st.set_page_config(page_title="Ghostbuster", layout="wide")
st.title("👻 Ghostbuster - Mobile SIGINT DF Tracker")

st.sidebar.header("📡 Signal Options")
frequency = st.sidebar.selectbox("Choose frequency to track (MHz):", [433.92, 915.0, 2400.0, 2450.0])
iq_record = st.sidebar.checkbox("Record IQ Samples")
chase_mode = st.sidebar.button("🚗 Engage Chase Mode")

st.sidebar.markdown("---")

# --------- LOCATION AND COMPASS (FROM BROWSER) ---------
st.subheader("📍 Current Position & Heading")

st.markdown("""
<script>
function sendPosition() {
    navigator.geolocation.getCurrentPosition(pos => {
        const coords = {
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            heading: pos.coords.heading || 0
        }
        fetch("/location", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(coords)
        });
    });
}
setInterval(sendPosition, 5000);
</script>
""", unsafe_allow_html=True)

# Mock/fallback location for desktop use
lat = st.session_state.get("lat", 36.8529)
lon = st.session_state.get("lon", -75.9780)
heading = st.session_state.get("heading", 0)

# Display current location info
st.write(f"Latitude: {lat:.5f}")
st.write(f"Longitude: {lon:.5f}")
st.write(f"Heading: {heading:.1f}°")

# --------- HACKRF SIGNAL STRENGTH ---------
def get_rssi(frequency_mhz):
    try:
        # Replace this with real logic for your HackRF signal strength measurement
        # This example simulates RSSI
        return -50 + (frequency_mhz % 10)  # fake signal value
    except Exception as e:
        st.error(f"Error reading HackRF: {e}")
        return None

rssi = get_rssi(frequency)

# --------- DATA LOGGING ---------
data = pd.DataFrame({
    'lat': [lat],
    'lon': [lon],
    'rssi': [rssi],
    'time': [datetime.datetime.now().isoformat()]
})

# --------- MAP DISPLAY ---------
st.subheader("📡 Signal Strength Map")
map_center = [data['lat'].mean(), data['lon'].mean()]
m = folium.Map(location=map_center, zoom_start=16)

for _, row in data.iterrows():
    color = "green" if row.rssi > -50 else "orange" if row.rssi > -60 else "red"
    folium.Circle(
        location=[row.lat, row.lon],
        radius=8,
        color=color,
        fill=True,
        fill_opacity=0.7
    ).add_to(m)

st_folium(m, height=500)

# --------- OPENAI LLM ANALYSIS ---------
st.subheader("🤖 LLM Signal Recommendations")
if st.button("🔍 Analyze Signals with LLM"):
    messages = [
        {"role": "system", "content": "You're a SIGINT specialist helping pick which RF signal to chase."},
        {"role": "user", "content": f"Here are the signals: {data.to_dict(orient='records')}. Based on signal strength and findability, which should I track and why?"}
    ]
    response = client.chat.completions.create(
        model="gpt-4",
        messages=messages
    )
    st.write(response.choices[0].message.content)

# --------- OPENAI TTS ---------
st.subheader("🗣️ Voice Guidance")
def speak(text):
    audio_response = client.audio.speech.create(
        model="tts-1",
        voice="nova",
        input=text
    )
    audio_path = "tts_output.mp3"
    with open(audio_path, "wb") as f:
        f.write(audio_response.content)
    with open(audio_path, "rb") as audio_file:
        audio_bytes = audio_file.read()
        st.audio(audio_bytes, format="audio/mp3")

if st.button("📢 Say Recommendation"):
    speak("Signal at 433 megahertz is strongest. Recommend driving north for better bearing.")

# --------- IQ Recording ---------
if chase_mode and iq_record:
    st.info(f"Recording IQ samples at {frequency} MHz...")
    iq_path = os.path.join(IQ_DIR, f"{frequency}MHz_{datetime.datetime.now().isoformat()}.iq")
    try:
        subprocess.Popen(["hackrf_transfer", "-r", iq_path, "-f", str(int(frequency * 1e6)), "-n", "10000000"])
        st.success(f"Recording started: {iq_path}")
    except Exception as e:
        st.error(f"HackRF error: {e}")

# --------- FOOTER ---------
st.markdown("---")
st.caption("Ghostbuster v0.2 – Live GPS, Compass & HackRF integration 🚗")
