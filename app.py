import os
import io
import httpx
import pdfplumber
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

IMPORTANTE: SOLO clasifica transacciones que aparecen EXPLÍCITAMENTE en el texto.
NO inventes transacciones. NO agregues ejemplos."""


def extract_pdf_text(file_bytes):
    """Extrae texto del PDF con pdfplumber — más limpio que PDF.js"""
    text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


def chunk_text(text, max_chars=12000):
    """Divide el texto en chunks por líneas para no perder transacciones"""
    lines = text.split("\n")
    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) > max_chars:
            if current:
                chunks.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        chunks.append(current)
    return chunks


def call_anthropic_text(prompt, system=None):
    """Llama a Haiku con texto plano — barato y preciso"""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 8096,
        "system": system or SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}]
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

    file_bytes = request.files["file"].read()

    try:
        # Extraer texto con pdfplumber
        text = extract_pdf_text(file_bytes)

        if not text or len(text.strip()) < 50:
            return jsonify({"error": "No se pudo extraer texto del PDF. Puede ser un PDF escaneado."}), 400

        # Dividir en chunks si el texto es muy largo
        chunks = chunk_text(text, max_chars=14000)

        results = []
        for i, chunk in enumerate(chunks):
            part = "primera parte" if i == 0 else f"parte {i+1} de {len(chunks)}"
            prompt = f"""Clasifica TODAS las transacciones de esta {part} del estado de cuenta.
SOLO incluye transacciones que aparezcan explícitamente. NO inventes nada.

{chunk}"""
            result = call_anthropic_text(prompt)
            results.append(result)

        combined = "\n".join(results)
        return jsonify({"result": combined})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"error": "Sin mensajes"}), 400
    try:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "messages": messages
        }
        with httpx.Client(timeout=60) as client:
            resp = client.post(API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            return jsonify({"result": resp.json()["content"][0]["text"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting ContaBot on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
