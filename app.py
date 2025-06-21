import os
import sys
import io
import csv
import base64
import requests
import logging
import threading
import time
import tempfile
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify, make_response
from pydub import AudioSegment

# Укажи свой реальный путь к папке BirdNET-Analyzer, если нужно
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "BirdNET-Analyzer"))

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
            # Сохраняем аудио с правильным расширением .m4a (если нужно поменяй на .aac)
            input_path = os.path.join(tmpdir, "input.m4a")
            wav_path = os.path.join(tmpdir, "input.wav")
            with open(input_path, "wb") as f:
                f.write(audio_bytes)

            # Конвертация в WAV 16kHz PCM 16-bit
            sound = AudioSegment.from_file(input_path, format="mp4")
            sound.export(wav_path, format="wav", parameters=["-acodec", "pcm_s16le", "-ar", "16000"])

            week = datetime.utcnow().isocalendar().week
            lat, lon = 0.0, 0.0  # заменить при необходимости

            output_dir = os.path.join(tmpdir, "out")
            os.makedirs(output_dir, exist_ok=True)

            # Запуск BirdNET-Analyzer с захватом вывода
            result = subprocess.run([
                "python3", "-m", "birdnet_analyzer.cli",
                "--input", wav_path,
                "--output", output_dir,
                "--lat", str(lat),
                "--lon", str(lon),
                "--week", str(week),
                "--language", "ru",
                "--min_conf", "0.25"
            ], capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"BirdNET-Analyzer stdout:\n{result.stdout}")
                logger.error(f"BirdNET-Analyzer stderr:\n{result.stderr}")
                return cors_response({
                    "error": "BirdNET-Analyzer execution failed",
                    "details": result.stderr.strip()
                }, 500)

            csv_file = os.path.join(output_dir, os.path.basename(wav_path) + "_Results.csv")
            if not os.path.exists(csv_file):
                return cors_response({"response": "⚠️ No detections or audio too short/noisy."})

            with open(csv_file, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            if not rows:
                return cors_response({"response": "⚠️ No detections."})

            best = max(rows, key=lambda r: float(r["Confidence"]))
            response_text = (
                f"1. Вид: {best['Common Name']} ({best['Scientific Name']})\n"
                f"2. Уверенность: {round(float(best['Confidence']) * 100, 1)}%\n"
                f"3. Источник: BirdNET-Analyzer"
            )
            return cors_response({"response": response_text})

    except subprocess.CalledProcessError as e:
        logger.error(f"Analyzer failed with CalledProcessError: {e}")
        return cors_response({"error": "BirdNET-Analyzer execution failed"}, 500)
    except Exception as e:
        logger.error(f"Audio processing error: {e}")
        return cors_response({"error": f"Server error: {e}"}, 500)

if __name__ == "__main__":
    start_keep_alive()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
