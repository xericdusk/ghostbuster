import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import datetime
import openai
import base64
import os
import subprocess
import numpy as np
from streamlit_js_eval import streamlit_js_eval

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

# --------- LOCATION ---------
st.subheader("📍 Current Position & Heading")
location = streamlit_js_eval(
    js_expressions="navigator.geolocation.getCurrentPosition((pos) => ({lat: pos.coords.latitude, lon: pos.coords.longitude}))",
    key="get_browser_location"
)

if location and isinstance(location, dict) and "lat" in location:
    st.session_state["lat"] = location["lat"]
    st.session_state["lon"] = location["lon"]

lat = st.session_state.get("lat", 36.8529)
lon = st.session_state.get("lon", -75.9780)
heading = st.session_state.get("heading", 0)

st.write(f"Latitude: {lat:.5f}, Longitude: {lon:.5f}, Heading: {heading:.1f}°")

# --------- HACKRF SIGNAL STRENGTH (Simulated) ---------
def get_rssi_from_hackrf(freq_mhz):
    try:
        return -60 + int(freq_mhz) % 5
    except Exception as e:
        st.error(f"HackRF RSSI Error: {e}")
        return -100

rssi = get_rssi_from_hackrf(frequency)

# --------- DATA LOGGING ---------
st.session_state.setdefault("history", [])
current_entry = {
    'lat': lat,
    'lon': lon,
    'rssi': rssi,
    'time': datetime.datetime.now().isoformat()
}
st.session_state.history.append(current_entry)
data = pd.DataFrame(st.session_state.history)

# --------- MAP DISPLAY ---------
st.subheader("📡 Signal Strength Map")

# Cache the map object to prevent reinitialization
@st.cache_resource
def get_base_map(lat, lon):
    return folium.Map(location=[lat, lon], zoom_start=16)

# Initialize or retrieve the map
if "map_initialized" not in st.session_state:
    st.session_state["map"] = get_base_map(lat, lon)
    st.session_state["map_initialized"] = True
    st.session_state["last_markers"] = set()  # Track markers to avoid duplicates

m = st.session_state["map"]

# SUV icon
suv_icon_url = "https://cdn-icons-png.flaticon.com/512/743/743920.png"
suv_key = f"suv_{lat}_{lon}"  # Unique key for the SUV marker
if suv_key not in st.session_state["last_markers"]:
    folium.Marker(
        location=[lat, lon],
        icon=folium.CustomIcon(suv_icon_url, icon_size=(30, 30)),
        popup="Your Location"
    ).add_to(m)
    st.session_state["last_markers"].add(suv_key)

# Add signal strength circles, avoiding duplicates
for _, row in data.iterrows():
    marker_key = f"circle_{row.lat}_{row.lon}_{row.rssi}"
    if marker_key not in st.session_state["last_markers"]:
        color = "green" if row.rssi > -50 else "orange" if row.rssi > -60 else "red"
        folium.Circle(
            location=[row.lat, row.lon],
            radius=6,
            color=color,
            fill=True,
            fill_opacity=0.6
        ).add_to(m)
        st.session_state["last_markers"].add(marker_key)

# Render the map with a fixed key to minimize re-rendering
map_output = st_folium(m, height=500, width=700, key="stable_map")

# Debug info
st.write(f"Map center: {m.location}, Markers: {len(st.session_state['last_markers'])}")

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
    try:
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
    except Exception as e:
        st.error(f"TTS Error: {e}")

if st.button("📢 Say Recommendation"):
    speak("Signal at 433 megahertz is strongest. Recommend driving north for better bearing.")

# --------- IQ Recording ---------
if chase_mode:
    st.success("🚗 Chase Mode Activated! Logging movement + signal...")
    if iq_record:
        st.info(f"Recording IQ samples at {frequency} MHz...")
        iq_path = os.path.join(IQ_DIR, f"{frequency}MHz_{datetime.datetime.now().isoformat()}.iq")
        try:
            subprocess.Popen(["hackrf_transfer", "-r", iq_path, "-f", str(int(frequency * 1e6)), "-n", "10000000"])
            st.success(f"Recording started: {iq_path}")
        except Exception as e:
            st.error(f"HackRF error: {e}")

# --------- FOOTER ---------
st.markdown("---")
st.caption("Ghostbuster v0.3 – Real-time DF, GPS, HackRF, TTS 🚙")