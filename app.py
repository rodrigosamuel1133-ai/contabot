import os
import base64
import anthropic
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """Eres ContaBot, un asistente contable inteligente. Analiza estados de cuenta bancarios y clasifica TODAS las transacciones.

Para cada transacción usa este formato exacto (una por línea):
[TX:{"tipo":"INGRESO|GASTO","monto":0.00,"descripcion":"descripción corta","categoria":"categoría","fecha":"MM/DD/AA"}]

Categorías para INGRESOS: Servicios, Square/POS, Zelle Recibido, Depósito
Categorías para GASTOS: Renta/Arrendamiento, Proveedores, Telecomunicaciones, Tarjeta de Crédito, Nómina, Pagos/Varios, Servicios Financieros

Después de todos los [TX:...], escribe un resumen breve en español con:
- Total ingresos
- Total gastos  
- Balance neto
- Observación más importante

NO omitas ninguna transacción. Procesa absolutamente todas las que aparezcan en el documento."""


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/process-pdf", methods=["POST"])
def process_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No se recibió archivo"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Archivo vacío"}), 400

    file_bytes = file.read()
    file_b64 = base64.standard_b64encode(file_bytes).decode("utf-8")

    ext = file.filename.rsplit(".", 1)[-1].lower()

    if ext == "pdf":
        content = [
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
        ]
    else:
        return jsonify({"error": "Solo se aceptan archivos PDF por este endpoint"}), 400

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    raw = message.content[0].text
    return jsonify({"result": raw})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"error": "Sin mensajes"}), 400

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return jsonify({"result": response.content[0].text})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
