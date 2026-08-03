import os
import base64
import httpx
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Eres ContaBot, asistente contable IRS Schedule C.

Formato obligatorio por transacción (una por línea):
[TX:{"tipo":"INGRESO|GASTO","monto":0.00,"descripcion":"descripción","categoria":"categoría","linea":"ING|L8|L9|L10|L11|L15|L16a|L16b|L17|L18|L20a|L20b|L21|L22|L23|L24a|L24b|L25|L26|L27a|L30","fecha":"MM/DD/AA"}]

INGRESOS → linea: ING, categoria: Ingresos Brutos del Negocio
GASTOS → línea Schedule C:
L8=Publicidad, L9=Vehículo, L10=Comisiones, L11=Mano de obra contrato
L15=Seguros, L16a=Interés hipoteca, L16b=Interés otros
L17=Legal/Profesional, L18=Gastos de Oficina, L20a=Alquiler vehículo/equipo
L20b=Alquiler propiedad comercial, L21=Reparaciones y Mantenimiento
L22=Suministros, L23=Impuestos y Licencias, L24a=Viajes
L24b=Comidas Deducibles, L25=Servicios Públicos, L26=Salarios
L27a=Otros Gastos, L30=Uso Hogar Negocio

Reglas:
- Zelle/Square RECIBIDO = INGRESO (ING)
- Zelle ENVIADO a persona = L26 (Salarios)
- Pago a empresa/LLC = L27a (Otros Gastos)
- Renta comercial = L20b
- Teléfono/internet/electricidad = L25
- Seguro = L15
- Tarjeta de crédito = L27a

IMPORTANTE: SOLO clasifica transacciones que aparecen EXPLÍCITAMENTE en el documento.
NO inventes ni agregues transacciones que no estén en el estado de cuenta.
NO agregues transacciones de ejemplo."""


def call_anthropic(messages, pdf_b64=None, instruccion=None, model="claude-haiku-4-5-20251001"):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if pdf_b64:
        headers["anthropic-beta"] = "pdfs-2024-09-25"
        messages = [{"role": "user", "content": [
            {"type": "document", "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_b64
            }},
            {"type": "text", "text": instruccion}
        ]}]
    payload = {
        "model": model,
        "max_tokens": 8096,
        "system": SYSTEM_PROMPT,
        "messages": messages
    }
    with httpx.Client(timeout=180) as client:
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
        result1 = call_anthropic([], pdf_b64=file_b64,
            instruccion="Clasifica ÚNICAMENTE los INGRESOS que aparecen en este estado de cuenta (depósitos, Zelle recibido, Square POS, créditos). NO incluyas gastos. NO inventes transacciones. SOLO las que están en el documento.",
            model="claude-sonnet-4-6")
        result2 = call_anthropic([], pdf_b64=file_b64,
            instruccion="Clasifica ÚNICAMENTE los GASTOS que aparecen en este estado de cuenta (débitos, Zelle enviado, pagos, retiros ATM, subtracciones). NO incluyas ingresos. NO inventes transacciones. SOLO las que están en el documento. Usa líneas IRS Schedule C.",
            model="claude-sonnet-4-6")
        return jsonify({"result": result1 + "\n" + result2})
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
    print(f"Starting ContaBot on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
