from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

@app.route("/", methods=["GET"])
def home():
    return "✅ Gemini Proxy Server is running"

@app.route("/", methods=["POST"])
def generate():
    data = request.get_json()
    prompt = data.get("prompt")
    image_b64 = data.get("image_base64")

    if not prompt or not image_b64:
        return jsonify({"error": "Missing prompt or image_base64"}), 400

    gemini_payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_b64
                        }
                    }
                ]
            }
        ]
    }

    try:
        res = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=gemini_payload,
            timeout=20
        )

        if res.status_code == 200:
            result = res.json()
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            return jsonify({"response": text})
        else:
            return jsonify({"error": "Gemini API error", "details": res.text}), res.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500
