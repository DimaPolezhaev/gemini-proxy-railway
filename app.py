import os
import io
import base64
import requests
import logging
import threading
import time
import tempfile
from datetime import datetime, timezone
from flask import Flask, request, jsonify, make_response
from pydub import AudioSegment

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ENV variables ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BIRDWEATHER_STATION_TOKEN = os.getenv("BIRDWEATHER_STATION_TOKEN")
BASE_URL = os.getenv("BIRDWEATHER_API_URL", "https://app.birdweather.com/api/v1")

# === Utility ===
def cors_response(payload, status=200):
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

def start_keep_alive():
    def loop():
        while True:
            url = os.getenv("APP_URL")
            if url:
                try:
                    requests.get(f"{url}/ping", timeout=5)
                    logger.info("⏰ Wakeup ping")
                except Exception as e:
                    logger.warning(f"Wakeup failed: {e}")
            time.sleep(300)
    threading.Thread(target=loop, daemon=True).start()

# === Routes ===
@app.route("/ping", methods=["GET", "OPTIONS"])
def ping():
    if request.method == "OPTIONS":
        return cors_response({})
    return cors_response({"status": "alive"})

@app.route("/", methods=["GET", "OPTIONS"])
def home():
    if request.method == "OPTIONS":
        return cors_response({})
    return cors_response({"status": "✅ Server is running"})

@app.route("/generate", methods=["POST", "OPTIONS"])
def generate_image():
    if request.method == "OPTIONS":
        return cors_response({})

    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt")
    image_b64 = data.get("image_base64")

    if not prompt or not image_b64:
        return cors_response({"error": "Prompt or image not provided"}, 400)
    if len(image_b64) > 4_000_000:
        return cors_response({"error": "Image size exceeds 4MB"}, 413)

    payload = {
        "contents": [
            {"role": "user", "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}}
            ]}
        ]
    }
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        if resp.status_code != 200:
            return cors_response({"error": "Gemini API error", "details": resp.text}, resp.status_code)
        result = resp.json()
        text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if not text.strip():
            return cors_response({"error": "Empty response from Gemini"}, 502)
        return cors_response({"response": text})
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return cors_response({"error": f"Server error: {e}"}, 500)

@app.route("/generate_audio", methods=["POST", "OPTIONS"])
def generate_audio():
    if request.method == "OPTIONS":
        return cors_response({})
    data = request.get_json(silent=True) or {}
    audio_b64 = data.get("audio_base64")
    if not audio_b64:
        return cors_response({"error": "audio_base64 not provided"}, 400)
    try:
        audio_bytes = base64.b64decode(audio_b64)
        if len(audio_bytes) < 500:
            return cors_response({"error": "⚠️ Audio too short or empty"}, 400)

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "input.aac")
            flac_path = os.path.join(tmpdir, "input.flac")
            with open(in_path, "wb") as f:
                f.write(audio_bytes)

            # decode AAC or fallback to m4a
            try:
                audio = AudioSegment.from_file(in_path, format="aac")
            except Exception:
                audio = AudioSegment.from_file(in_path, format="m4a")

            audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
            audio.export(flac_path, format="flac")

            # POST soundscape
            ts = datetime.now(timezone.utc).isoformat()
            upload_url = f"{BASE_URL}/stations/{BIRDWEATHER_STATION_TOKEN}/soundscapes?timestamp={ts}"
            with open(flac_path, "rb") as f:
                files = {"audio": ("input.flac", f, "audio/flac")}  
                resp = requests.post(upload_url, files=files, timeout=15)

            # Accept 200 or 201
            if resp.status_code not in (200, 201):
                return cors_response({"error": "Upload failed", "details": resp.text}, 500)

            # Fetch detections
            det_url = f"{BASE_URL}/stations/{BIRDWEATHER_STATION_TOKEN}/detections?limit=1"
            det_resp = requests.get(det_url, timeout=10)
            if det_resp.status_code != 200:
                return cors_response({"error": "Fetch detections failed", "details": det_resp.text}, 500)

            det_json = det_resp.json().get("detections", [])
            if not det_json:
                return cors_response({"response": "⚠️ No bird sounds detected."})

            best = max(det_json, key=lambda d: d.get("confidence", 0))
            name = best.get("species", {}).get("common_name", "Unknown")
            conf = round(best.get("confidence", 0) * 100, 1)
            return cors_response({"response": f"1. Вид: {name}\n2. Уверенность: {conf}%\n3. Источник: BirdWeather"})
    except Exception as e:
        logger.error(f"Audio error: {e}")
        return cors_response({"error": f"Server error: {e}"}, 500)

if __name__ == "__main__":
    start_keep_alive()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
