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

# ENV-переменные
BIRDWEATHER_TOKEN = os.getenv("BIRDWEATHER_STATION_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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

        with tempfile.TemporaryDirectory() as tmpdir:
            flac_path = os.path.join(tmpdir, "input.flac")

            # Сохраняем как FLAC
            with open(flac_path, "wb") as f:
                f.write(audio_bytes)

            # BirdWeather API
            timestamp = datetime.now(timezone.utc).isoformat()
            url = f"https://app.birdweather.com/api/v1/stations/{BIRDWEATHER_TOKEN}/soundscapes?timestamp={timestamp}"

            with open(flac_path, "rb") as f:
                files = {"audio": ("input.flac", f, "audio/flac")}
                response = requests.post(url, files=files, timeout=15)

            if response.status_code != 200:
                logger.error(f"BirdWeather API error: {response.text}")
                return cors_response({"error": "BirdWeather API failed", "details": response.text}, 500)

            result = response.json()
            detections = result.get("detections", [])

            if not detections:
                return cors_response({"response": "⚠️ Голоса птиц не обнаружены."})

            best = max(detections, key=lambda d: float(d.get("confidence", 0)))
            name = best.get("common_name", "Неизвестно")
            conf = round(float(best.get("confidence", 0)) * 100, 1)

            return cors_response({
                "response": f"1. Вид: {name}\n2. Уверенность: {conf}%\n3. Источник: BirdWeather"
            })

    except Exception as e:
        logger.error(f"Audio error: {e}")
        return cors_response({"error": f"Server error: {e}"}, 500)

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
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}}
                ]
            }
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

if __name__ == "__main__":
    start_keep_alive()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
