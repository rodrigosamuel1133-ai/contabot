import os
import base64
import httpx
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Eres ContaBot, un asistente contable especializado en taxes para el IRS (Schedule C).

Clasifica TODAS las transacciones del estado de cuenta usando las categorías exactas del IRS Schedule C.

Para cada transacción usa este formato exacto:
[TX:{"tipo":"INGRESO|GASTO","monto":0.00,"descripcion":"descripción","categoria":"categoría IRS","linea":"línea Schedule C","fecha":"MM/DD/AA"}]

CATEGORÍAS DE INGRESOS:
- Ingresos Brutos del Negocio

CATEGORÍAS DE GASTOS (Schedule C — IRS):
- Línea 8: Publicidad (Advertising)
- Línea 9: Gastos de Vehículo (Car and truck expenses)
- Línea 10: Comisiones y Honorarios (Commissions and fees)
- Línea 11: Mano de Obra por Contrato (Contract labor)
- Línea 13: Depreciación Sección 179 (Depreciation)
- Línea 14: Beneficios para Empleados (Employee benefit programs)
- Línea 15: Seguros — No Salud (Insurance other than health)
- Línea 16a: Intereses — Hipoteca (Interest Mortgage)
- Línea 16b: Intereses — Otros (Interest Other)
- Línea 17: Servicios Legales y Profesionales (Legal and professional services)
- Línea 18: Gastos de Oficina (Office expense)
- Línea 20a: Alquiler — Vehículos y Equipo (Rent lease vehicles equipment)
- Línea 20b: Alquiler — Propiedad Comercial (Rent lease business property)
- Línea 21: Reparaciones y Mantenimiento (Repairs and maintenance)
- Línea 22: Suministros (Supplies)
- Línea 23: Impuestos y Licencias (Taxes and licenses)
- Línea 24a: Viajes (Travel)
- Línea 24b: Comidas Deducibles (Deductible meals)
- Línea 25: Servicios Públicos (Utilities)
- Línea 26: Salarios (Wages)
- Línea 27a: Otros Gastos (Other expenses)
- Línea 30: Uso Comercial del Hogar (Business use of home)

REGLAS DE CLASIFICACIÓN:
- Pagos Zelle RECIBIDOS = INGRESO (Ingresos Brutos del Negocio)
- Pagos Square/POS = INGRESO (Ingresos Brutos del Negocio)
- Pagos Zelle ENVIADOS a personas = Línea 26: Salarios o Línea 11: Mano de Obra por Contrato
- Pagos a empresas proveedoras = Línea 27a: Otros Gastos
- Renta/Arrendamiento comercial = Línea 20b: Alquiler — Propiedad Comercial
- Electricidad/Agua/Internet = Línea 25: Servicios Públicos
- Teléfono/Wireless = Línea 25: Servicios Públicos
- Tarjeta de crédito pagos = Línea 27a: Otros Gastos
- Seguros = Línea 15: Seguros — No Salud
- Publicidad/Marketing = Línea 8: Publicidad

Al final escribe un resumen con:
- Total Ingresos
- Total por cada línea del Schedule C con gastos
- Balance Neto
- Nota sobre qué transacciones podrían necesitar verificación"""


def call_anthropic(messages, pdf_b64=None, instruccion=None):
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
            {"type": "text", "text": instruccion or "Clasifica TODAS las transacciones usando las categorías del IRS Schedule C."}
        ]}]
    payload = {
        "model": "claude-sonnet-4-6",
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
            instruccion="Clasifica SOLO los INGRESOS (depósitos, Zelle recibido, Square) usando categorías IRS Schedule C.")
        result2 = call_anthropic([], pdf_b64=file_b64,
            instruccion="Clasifica SOLO los GASTOS (retiros, pagos, Zelle enviado, débitos) usando categorías IRS Schedule C. Incluye la línea del Schedule C para cada gasto.")
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
