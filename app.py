import os
import base64
import httpx
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Eres ContaBot, un asistente contable. Analiza estados de cuenta y clasifica TODAS las transacciones.

Para cada transacción usa este formato exacto:
[TX:{"tipo":"INGRESO|GASTO","monto":0.00,"descripcion":"descripción","categoria":"categoría","fecha":"MM/DD/AA"}]

Categorías INGRESOS: Servicios, Square/POS, Zelle Recibido, Depósito
Categorías GASTOS: Renta, Proveedores, Telecomunicaciones, Tarjeta, Nómina, Pagos/Varios

Al final escribe resumen con total ingresos, gastos y balance."""


def call_anthropic(messages, pdf_b64=None):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if pdf_b64:
        headers["anthropic-beta"] = "pdfs-2024-09-25"
        messages = [{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
            {"type": "text", "text": "Clasifica TODAS las transacciones de este estado de cuenta."}
        ]}]
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": messages
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
        return jsonify({"error": "No file"}), 400
    file_b64 = base64.standard_b64encode(request.files["file"].read()).decode("utf-8")
    try:
        result = call_anthropic([], pdf_b64=file_b64)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    try:
        result = call_anthropic(data.get("messages", []))
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
