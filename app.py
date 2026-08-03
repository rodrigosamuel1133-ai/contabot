import os
import base64
import json
import httpx
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_URL = "https://api.anthropic.com/v1/messages"
HEADERS = {
    "x-api-key": ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "pdfs-2024-09-25",
    "content-type": "application/json",
}

SYSTEM_PROMPT = """Eres ContaBot, un asistente contable inteligente. Analiza estados de cuenta bancarios y clasifica TODAS las transacciones.

Para cada transacción usa este formato exacto (una por línea):
[TX:{"tipo":"INGRESO|GASTO","monto":0.00,"descripcion":"descripción corta","categoria":"categoría","fecha":"MM/DD/AA"}]

Categorías para INGRESOS: Servicios, Square/POS, Zelle Recibido, Depósito
Categorías para GASTOS: Renta/Arrendamiento, Proveedores, Telecomunicaciones, Tarjeta de Crédito, Nómina, Pagos/Varios, Servicios Financieros

Después de todos los [TX:...], escribe un resumen breve en español con total ingresos, total gastos y balance neto.
NO omitas ninguna transacción."""


def call_anthropic(messages, use_pdf_beta=False):
    headers = dict(HEADERS)
    headers["x-api-key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    if not use_pdf_beta:
        headers.pop("anthropic-beta", None)

    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": messages,
    }

    with httpx.Client(timeout=120) as client:
        resp = client.post(API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/process-pdf", methods=["POST"])
def process_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No se recibió archivo"}), 400

    file = request.files["file"]
    file_bytes = file.read()
    file_b64 = base64.standard_b64encode(file_bytes).decode("utf-8")

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": file_b64,
                    },
                },
                {
                    "type": "text",
                    "text": "Analiza este estado de cuenta bancario completo y clasifica TODAS las transacciones sin omitir ninguna.",
                },
            ],
        }
    ]

    try:
        result = call_anthropic(messages, use_pdf_beta=True)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"error": "Sin mensajes"}), 400
    try:
        result = call_anthropic(messages)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
