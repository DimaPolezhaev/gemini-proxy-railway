import os
import io
import base64
import requests
import logging
import threading
import time
import tarfile
from flask import Flask, request, jsonify, make_response

# === Автоматическая загрузка ffmpeg ===
def ensure_ffmpeg():
    if not os.path.exists("ffmpeg/ffmpeg"):
        print("⬇️  Скачиваем ffmpeg...")
        os.makedirs("ffmpeg", exist_ok=True)

        # Скачиваем архив
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        archive_path = "ffmpeg.tar.xz"

        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(archive_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        # Распаковываем
        with tarfile.open(archive_path, "r:xz") as tar:
            members = [m for m in tar.getmembers() if "/" in m.name and not m.isdir()]
            for m in members:
                name = os.path.basename(m.name)
                m.name = name
                tar.extract(m, path="ffmpeg")

        os.remove(archive_path)
        print("✅ ffmpeg установлен")

    # Обновляем PATH
    os.environ["PATH"] = os.path.abspath("ffmpeg") + os.pathsep + os.environ["PATH"]

ensure_ffmpeg()

# === Flask-приложение ===
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Переменные окружения ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# === CORS ===
def cors_response(payload, status=200):
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

# === Keep-alive для Railway ===
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

# === Роуты ===

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
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {
                        "mime_type": "image/jpeg",
                        "data": image_b64
                    }}
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
