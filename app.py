from flask import Flask, request, jsonify, make_response
from birdnetlib.analyzer import Analyzer
from birdnetlib import Recording
import tempfile
import base64
import os
import logging

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def cors_response(payload, status=200):
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/", methods=["GET"])
def home():
    return cors_response({"status": "✅ BirdNET сервер запущен"})


@app.route("/generate_audio", methods=["POST", "OPTIONS"])
def generate_audio():
    if request.method == "OPTIONS":
        return cors_response({})

    try:
        data = request.get_json(silent=True) or {}
        audio_base64 = data.get("audio_base64")

        if not audio_base64:
            return cors_response({"error": "audio_base64 не передан"}, 400)

        # Декодируем в .wav файл
        audio_bytes = base64.b64decode(audio_base64)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            temp_audio.write(audio_bytes)
            temp_audio_path = temp_audio.name

        # Анализ
        analyzer = Analyzer(min_confidence=0.5)
        recording = Recording(analyzer=analyzer, file_path=temp_audio_path)
        recording.analyze()

        os.remove(temp_audio_path)  # Удалим файл

        if not recording.detections:
            return cors_response({
                "response": "⚠️ Птицы не обнаружены или запись слишком шумная/короткая."
            })

        best = max(recording.detections, key=lambda d: d["confidence"])
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
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
