from flask import Flask, request, jsonify, make_response
import os
import requests
import logging
import threading
import time
import base64

app = Flask(__name__)

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Переменные окружения
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Периодическая активность (пинг к самому себе)
def start_keep_alive():
    def loop():
        while True:
            try:
                url = os.getenv("APP_URL")
                if url:
                    requests.get(f"{url}/ping", timeout=5)
                    logger.info("⏰ Wakeup ping sent to self.")
                else:
                    logger.warning("⚠️ APP_URL environment variable not set.")
            except Exception as e:
                logger.warning(f"Wakeup ping failed: {e}")
            time.sleep(300)  # каждые 5 минут

    threading.Thread(target=loop, daemon=True).start()

# CORS-ответ
def cors_response(payload, status=200):
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

# Эндпоинт для проверки, что сервер жив
@app.route("/ping", methods=["GET", "OPTIONS"])
def ping():
    if request.method == "OPTIONS":
        return cors_response({})
    return cors_response({"status": "alive"})

# Главная страница
@app.route("/", methods=["GET", "OPTIONS"])
def home():
    if request.method == "OPTIONS":
        return cors_response({})
    return cors_response({"status": "✅ Gemini Proxy Server is running"})

# Эндпоинт для обработки изображений
@app.route("/generate", methods=["POST", "OPTIONS"])
def generate():
    if request.method == "OPTIONS":
        return cors_response({})

    try:
        data = request.get_json(silent=True) or {}
        prompt = data.get("prompt")
        image_base64 = data.get("image_base64")

        if not prompt or not image_base64:
            logger.warning("❗ Отсутствует prompt или image_base64")
            return cors_response({"error": "Prompt or image not provided"}, 400)

        if len(image_base64) > 4_000_000:
            logger.warning(f"🚫 Изображение превышает 4MB ({len(image_base64)} байт)")
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

        logger.info("📡 Запрос к Gemini API (изображение)...")
        response = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=gemini_payload,
            timeout=7
        )

        logger.info(f"✅ Ответ от Gemini: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text.strip():
                return cors_response({"error": "Empty response from Gemini API"}, 502)
            return cors_response({"response": text})
        else:
            return cors_response({
                "error": "Gemini API error",
                "status_code": response.status_code,
                "details": response.text
            }, response.status_code)

    except requests.exceptions.Timeout:
        logger.error("⏱ Таймаут запроса")
        return cors_response({"error": "Request to Gemini API timed out"}, 504)
    except requests.exceptions.ConnectionError:
        logger.error("❌ Ошибка подключения к Gemini API")
        return cors_response({"error": "Connection error to Gemini API"}, 502)
    except requests.exceptions.RequestException as e:
        logger.error(f"⚠️ Общая ошибка запроса: {e}")
        return cors_response({"error": f"Request error: {str(e)}"}, 500)
    except Exception as e:
        logger.error(f"💥 Ошибка сервера: {e}")
        return cors_response({"error": f"Server error: {str(e)}"}, 500)

# Новый эндпоинт для обработки аудио
@app.route("/generate_audio", methods=["POST", "OPTIONS"])
def generate_audio():
    if request.method == "OPTIONS":
        return cors_response({})

    try:
        data = request.get_json(silent=True) or {}
        prompt = data.get("prompt")
        audio_base64 = data.get("audio_base64")

        if not prompt or not audio_base64:
            logger.warning("❗ Отсутствует prompt или audio_base64")
            return cors_response({"error": "Prompt or audio not provided"}, 400)

        if len(audio_base64) > 4_000_000:
            logger.warning(f"🚫 Аудио превышает 4MB ({len(audio_base64)} байт)")
            return cors_response({"error": "Audio size exceeds 4MB"}, 413)

        # Предполагаем, что Gemini API поддерживает аудио
        gemini_payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "audio/aac",  # Формат, используемый клиентом
                                "data": audio_base64
                            }
                        }
                    ]
                }
            ]
        }

        logger.info("📡 Запрос к Gemini API (аудио)...")
        response = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=gemini_payload,
            timeout=15  # Увеличенный таймаут для аудио
        )

        logger.info(f"✅ Ответ от Gemini (аудио): {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text.strip():
                return cors_response({"error": "Empty response from Gemini API"}, 502)
            return cors_response({"response": text})
        else:
            return cors_response({
                "error": "Gemini API error",
                "status_code": response.status_code,
                "details": response.text
            }, response.status_code)

    except requests.exceptions.Timeout:
        logger.error("⏱ Таймаут запроса (аудио)")
        return cors_response({"error": "Request to Gemini API timed out"}, 504)
    except requests.exceptions.ConnectionError:
        logger.error("❌ Ошибка подключения к Gemini API (аудио)")
        return cors_response({"error": "Connection error to Gemini API"}, 502)
    except requests.exceptions.RequestException as e:
        logger.error(f"⚠️ Общая ошибка запроса (аудио): {e}")
        return cors_response({"error": f"Request error: {str(e)}"}, 500)
    except Exception as e:
        logger.error(f"💥 Ошибка сервера (аудио): {e}")
        return cors_response({"error": f"Server error: {str(e)}"}, 500)

# Запуск сервера
if __name__ == "__main__":
    start_keep_alive()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)