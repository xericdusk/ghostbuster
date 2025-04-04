import streamlit as st
import pandas as pd
import folium
import datetime
import openai
import os
import subprocess
import time
import numpy as np
import streamlit.components.v1 as components
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
sweep_interval = st.sidebar.slider("Sweep Interval (seconds)", 5, 60, 30)

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

# --------- HACKRF FUNCTIONS ---------
def run_hackrf_sweep(start_freq, stop_freq, output_file):
    """Run hackrf_sweep and save output to a CSV file."""
    try:
        cmd = ["hackrf_sweep", "-f", f"{start_freq}:{stop_freq}", "-w", "1000000", "-l", "1"]
        with open(output_file, "w") as f:
            subprocess.run(cmd, stdout=f, text=True, timeout=10)
        return True
    except Exception as e:
        st.error(f"Sweep Error: {e}")
        return False

def parse_sweep_data(file_path):
    """Parse hackrf_sweep CSV output for candidate signals."""
    try:
        df = pd.read_csv(file_path, names=["date", "time", "start_freq", "end_freq", "samples", "dbm"])
        candidates = df.groupby(["start_freq", "end_freq"]).agg({"dbm": "max"}).reset_index()
        candidates = candidates[candidates["dbm"] > -60]  # Threshold for signals of interest
        return candidates
    except Exception as e:
        st.error(f"Parse Error: {e}")
        return pd.DataFrame()

def get_real_time_rssi(freq_mhz):
    """Get real-time RSSI for a specific frequency using hackrf_transfer."""
    try:
        iq_file = "temp.iq"
        cmd = ["hackrf_transfer", "-r", iq_file, "-f", str(int(freq_mhz * 1e6)), "-s", "2000000", "-n", "10000"]
        subprocess.run(cmd, timeout=2)
        # Read IQ samples (8-bit signed integers)
        with open(iq_file, "rb") as f:
            iq_data = np.fromfile(f, dtype=np.int8)
        # Separate I and Q (interleaved)
        i_samples = iq_data[0::2]
        q_samples = iq_data[1::2]
        # Calculate power in dBm
        power = 10 * np.log10(np.mean(i_samples**2 + q_samples**2)) - 30  # Rough conversion
        os.remove(iq_file)
        return power
    except Exception as e:
        st.error(f"Real-Time RSSI Error: {e}")
        return -100

# --------- INITIAL SWEEP ---------
st.session_state.setdefault("candidates", pd.DataFrame())
if "last_sweep" not in st.session_state:
    sweep_file = os.path.join(LOG_DIR, "initial_sweep.csv")
    if run_hackrf_sweep(1, 6000, sweep_file):  # Full 1 MHz to 6 GHz sweep
        st.session_state["candidates"] = parse_sweep_data(sweep_file)
        st.session_state["last_sweep"] = time.time()

# --------- PERIODIC SWEEP UPDATES ---------
current_time = time.time()
if "last_sweep" in st.session_state and (current_time - st.session_state["last_sweep"]) > sweep_interval:
    sweep_file = os.path.join(LOG_DIR, f"sweep_{int(current_time)}.csv")
    if run_hackrf_sweep(1, 6000, sweep_file):
        new_candidates = parse_sweep_data(sweep_file)
        st.session_state["candidates"] = pd.concat([st.session_state["candidates"], new_candidates]).drop_duplicates(subset=["start_freq"])
        st.session_state["last_sweep"] = current_time

# Display candidates
st.subheader("📡 Signal Candidates")
if not st.session_state["candidates"].empty:
    st.dataframe(st.session_state["candidates"])
    selected_freq = st.selectbox("Select a candidate to chase:", st.session_state["candidates"]["start_freq"])
else:
    st.write("No candidates found yet.")

# --------- DATA LOGGING ---------
st.session_state.setdefault("history", [])
if chase_mode and "selected_freq" in locals():
    rssi = get_real_time_rssi(selected_freq)
    current_entry = {
        "lat": lat,
        "lon": lon,
        "rssi": rssi,
        "time": datetime.datetime.now().isoformat(),
        "freq": selected_freq
    }
    st.session_state["history"].append(current_entry)
data = pd.DataFrame(st.session_state["history"])

# --------- MAP DISPLAY ---------
def generate_map(lat, lon, data):
    m = folium.Map(location=[lat, lon], zoom_start=16)
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
    return m._repr_html_()

if "last_lat" not in st.session_state or st.session_state["last_lat"] != lat or st.session_state["last_lon"] != lon:
    map_html = generate_map(lat, lon, data)
    st.session_state["map_html"] = map_html
    st.session_state["last_lat"] = lat
    st.session_state["last_lon"] = lon

components.html(st.session_state.get("map_html", generate_map(lat, lon, data)), height=500, width=700)

# --------- REAL-TIME RSSI IN CHASE MODE ---------
if chase_mode and "selected_freq" in locals():
    st.subheader("📊 Real-Time RSSI")
    rssi_placeholder = st.empty()
    stop_button = st.button("Stop Chase Mode")
    while chase_mode and not stop_button:  # Loop until stop button is pressed
        rssi = get_real_time_rssi(selected_freq)
        rssi_placeholder.write(f"Current RSSI: {rssi:.2f} dBm")
        time.sleep(1)  # Update every second
    if stop_button:
        st.write("Chase mode stopped.")

# --------- OPENAI LLM ANALYSIS ---------
st.subheader("🤖 LLM Signal Recommendations")
if st.button("🔍 Analyze Signals with LLM"):
    messages = [
        {"role": "system", "content": "You're a SIGINT specialist helping pick which RF signal to chase."},
        {"role": "user", "content": f"Here are the signals: {data.to_dict(orient='records')}. Based on signal strength and findability, which should I track and why?"}
    ]
    response = client.chat.completions.create(model="gpt-4", messages=messages)
    st.write(response.choices[0].message.content)

# --------- OPENAI TTS ---------
st.subheader("🗣️ Voice Guidance")
def speak(text):
    try:
        audio_response = client.audio.speech.create(model="tts-1", voice="nova", input=text)
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
if chase_mode and iq_record and "selected_freq" in locals():
    st.info(f"Recording IQ samples at {selected_freq} MHz...")
    iq_path = os.path.join(IQ_DIR, f"{selected_freq}MHz_{datetime.datetime.now().isoformat()}.iq")
    try:
        subprocess.Popen(["hackrf_transfer", "-r", iq_path, "-f", str(int(selected_freq * 1e6)), "-n", "10000000"])
        st.success(f"Recording started: {iq_path}")
    except Exception as e:
        st.error(f"HackRF error: {e}")

# --------- FOOTER ---------
st.markdown("---")
st.caption("Ghostbuster v0.4 – Real-time DF, GPS, HackRF, TTS 🚙")