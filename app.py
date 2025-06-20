from flask import Flask, request, jsonify, make_response
from birdnetlib.analyzer import Analyzer
from birdnetlib import Recording
import tempfile
import base64
import os
import logging
import requests
import threading
import time

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Gemini API настройки
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Keep-alive для Railway
def start_keep_alive():
    def loop():
        while True:
            try:
                url = os.getenv("APP_URL")
                if url:
                    requests.get(f"{url}/ping", timeout=5)
                    logger.info("⏰ Wakeup ping sent.")
            except Exception as e:
                logger.warning(f"Wakeup ping failed: {e}")
            time.sleep(300)
    threading.Thread(target=loop, daemon=True).start()


def cors_response(payload, status=200):
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


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

    try:
        data = request.get_json(silent=True) or {}
        prompt = data.get("prompt")
        image_base64 = data.get("image_base64")

        if not prompt or not image_base64:
            return cors_response({"error": "Prompt or image not provided"}, 400)

        if len(image_base64) > 4_000_000:
            return cors_response({"error": "Image size exceeds 4MB"}, 413)

        gemini_payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_base64
                            }
                        }
                    ]
                }
            ]
        }

        response = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=gemini_payload,
            timeout=10
        )

        if response.status_code == 200:
            result = response.json()
            text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text.strip():
                return cors_response({"error": "Empty response from Gemini"}, 502)
            return cors_response({"response": text})
        else:
            return cors_response({
                "error": "Gemini API error",
                "status_code": response.status_code,
                "details": response.text
            }, response.status_code)

    except Exception as e:
        logger.error(f"💥 Ошибка сервера (Gemini): {e}")
        return cors_response({"error": f"Server error: {str(e)}"}, 500)


@app.route("/generate_audio", methods=["POST", "OPTIONS"])
def generate_audio():
    if request.method == "OPTIONS":
        return cors_response({})

    try:
        data = request.get_json(silent=True) or {}
        audio_base64 = data.get("audio_base64")

        if not audio_base64:
            return cors_response({"error": "audio_base64 не передан"}, 400)

        audio_bytes = base64.b64decode(audio_base64)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            temp_audio.write(audio_bytes)
            temp_audio_path = temp_audio.name

        try:
            analyzer = Analyzer()
            recording = Recording(temp_audio_path, analyzer)
            recording.analyze()
        finally:
            os.remove(temp_audio_path)

        detections = [d for d in recording.detections if d["confidence"] >= 0.5]

        if not detections:
            return cors_response({
                "response": "⚠️ Птицы не обнаружены или запись слишком шумная/короткая."
            })

        best = max(detections, key=lambda d: d["confidence"])
        response_text = (
            f"1. Вид: {best['common_name']} ({best['scientific_name']})\n"
            f"2. Описание: BirdNET определил вид по голосу\n"
            f"3. Уверенность: {round(best['confidence'] * 100, 1)}%\n"
            f"4. Источник: BirdNET (локальный анализ)"
        )

        return cors_response({"response": response_text})

    except Exception as e:
        logger.error(f"Ошибка BirdNET: {e}")
        return cors_response({"error": f"Ошибка сервера: {str(e)}"}, 500)


if __name__ == "__main__":
    start_keep_alive()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)