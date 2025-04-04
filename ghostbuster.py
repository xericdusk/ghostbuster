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
import streamlit.components.v1 as components

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

# --------- LOCATION (Using JS watchPosition without reruns) ---------
st.subheader("📍 Current Position & Heading")

if "lat" not in st.session_state:
    st.session_state["lat"] = 36.8529
if "lon" not in st.session_state:
    st.session_state["lon"] = -75.9780

components.html("""
<script>
  const sendLocation = (lat, lon) => {
    const streamlitInput = window.parent.document.querySelector("iframe").contentWindow;
    streamlitInput.postMessage({
      isStreamlitMessage: true,
      type: "streamlit:setComponentValue",
      key: "location_update",
      value: JSON.stringify({ lat: lat, lon: lon }),
      fromPython: false
    }, "*");
  };
  
  navigator.geolocation.watchPosition(
    (position) => {
      const lat = position.coords.latitude;
      const lon = position.coords.longitude;
      sendLocation(lat, lon);
    }
  );
</script>
""", height=0)

location_update = st.query_params.get("location_update")

if location_update:
    try:
        coords = eval(location_update[0])
        st.session_state["lat"] = coords["lat"]
        st.session_state["lon"] = coords["lon"]
    except:
        pass

lat = st.session_state["lat"]
lon = st.session_state["lon"]
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
map_center = [lat, lon]
m = folium.Map(location=map_center, zoom_start=16)

# SUV icon
suv_icon_url = "https://cdn-icons-png.flaticon.com/512/743/743920.png"
folium.Marker(
    location=[lat, lon],
    icon=folium.CustomIcon(suv_icon_url, icon_size=(30, 30)),
    popup="Your Location"
).add_to(m)

for _, row in data.iterrows():
    color = "green" if row.rssi > -50 else "orange" if row.rssi > -60 else "red"
    folium.Circle(
        location=[row.lat, row.lon],
        radius=6,
        color=color,
        fill=True,
        fill_opacity=0.6
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
