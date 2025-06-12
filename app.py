from flask import Flask, request, jsonify, make_response
import os
import requests
import logging

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ключ и URL Gemini из переменных окружения
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def cors_response(payload, status=200):
    """Обёртка для JSON-ответа с CORS-заголовками."""
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

@app.route("/", methods=["GET", "OPTIONS"])
def home():
    if request.method == "OPTIONS":
        return cors_response({})
    return cors_response({"status": "✅ Gemini Proxy Server is running"})

@app.route("/generate", methods=["POST", "OPTIONS"])
def generate():
    if request.method == "OPTIONS":
        return cors_response({})

    try:
        data = request.get_json(silent=True) or {}
        user_prompt = data.get("prompt")
        image_base64 = data.get("image_base64")

        if not user_prompt or not image_base64:
            logger.error("Missing prompt or image_base64")
            return cors_response({"error": "Prompt or image not provided"}, 400)

        image_size = len(image_base64)
        logger.info(f"Размер image_base64: {image_size} байт")
        if image_size > 4_000_000:
            logger.error("Image too large")
            return cors_response({"error": "Image size exceeds 4MB limit"}, 413)

        gemini_request = {
            "contents": [
                {
                    "parts": [
                        {"text": user_prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_base64
                            }
                        }
                    ],
                    "role": "user"
                }
            ]
        }

        logger.info("Отправка запроса к Gemini API")
        response = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=gemini_request,
            timeout=7
        )

        logger.info(f"Ответ Gemini API: status={response.status_code}")

        if response.status_code == 200:
            result = response.json()
            text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text:
                logger.error("Empty text response")
                return cors_response({"error": "Empty response from Gemini API"}, 500)
            return cors_response({"response": text})
        else:
            logger.error(f"Gemini error: {response.status_code}, {response.text}")
            return cors_response({"error": "Gemini API error", "details": response.text}, response.status_code)

    except requests.exceptions.Timeout:
        logger.error("Request to Gemini API timed out")
        return cors_response({"error": "Request to Gemini API timed out"}, 504)
    except requests.exceptions.ConnectionError:
        logger.error("Connection error to Gemini API")
        return cors_response({"error": "Connection error to Gemini API"}, 502)
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return cors_response({"error": f"Request error: {str(e)}"}, 500)
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        return cors_response({"error": f"Server error: {str(e)}"}, 500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))  # Railway использует PORT
    app.run(host="0.0.0.0", port=port, debug=False)