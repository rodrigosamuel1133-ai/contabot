import os
import io
import re
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

IMPORTANTE: USA LOS MONTOS EXACTOS tal como aparecen en el estado de cuenta.
SOLO clasifica transacciones que aparecen EXPLÍCITAMENTE en el texto.
NO inventes transacciones. NO agregues ejemplos."""


def extract_pdf_text(file_bytes):
    """Extrae texto del PDF con pdfplumber"""
    text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


def extract_bank_summary(text):
    """
    Extrae los totales oficiales del banco del resumen del PDF.
    Usa los totales explícitos del banco para verificación precisa.
    """
    summary = {}

    # INGRESOS — busca el total explícito del banco primero
    ing_patterns = [
        r"Total deposits and other additions\s+\$?([\d,]+\.\d{2})",
        r"Total deposits\s+\$?([\d,]+\.\d{2})",
        r"Total credits\s+\$?([\d,]+\.\d{2})",
        r"Total créditos\s+\$?([\d,]+\.\d{2})",
        r"^Deposits and other additions\s+([\d,]+\.\d{2})\s*$",
    ]
    for pat in ing_patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if val > 0:
                    summary["deposits"] = val
                    break
            except:
                pass

    # GASTOS — busca total combinado primero, si no suma ATM + Other
    gas_combined = [
        r"Total withdrawals and other subtractions\s+\$?([\d,]+\.\d{2})",
        r"Total subtractions\s+\$?([\d,]+\.\d{2})",
        r"Total débitos\s+\$?([\d,]+\.\d{2})",
    ]
    for pat in gas_combined:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                summary["withdrawals"] = float(m.group(1).replace(",", ""))
                break
            except:
                pass

    # Si no encontró total combinado, suma líneas individuales del Account Summary
    if "withdrawals" not in summary:
        gas_lines = [
            r"^ATM and debit card subtractions\s+-?\$?([\d,]+\.\d{2})\s*$",
            r"^Other subtractions\s+-?\$?([\d,]+\.\d{2})\s*$",
            r"^Checks\s+-?\$?([\d,]+\.\d{2})\s*$",
            r"^Service fees\s+-?\$?([\d,]+\.\d{2})\s*$",
        ]
        total = 0.0
        found = False
        for pat in gas_lines:
            m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if m:
                try:
                    val = float(m.group(1).replace(",", ""))
                    if val > 0:
                        total += val
                        found = True
                except:
                    pass
        if found:
            summary["withdrawals"] = round(total, 2)

    return summary


def chunk_text(text, max_chars=14000):
    """Divide el texto en chunks por líneas"""
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


def call_anthropic_text(prompt, system=None, model="claude-haiku-4-5-20251001"):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 8096,
        "system": system or SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}]
    }
    with httpx.Client(timeout=120) as client:
        resp = client.post(API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


def parse_tx_totals(combined_text):
    """Suma los montos de los TX clasificados para verificación"""
    import json
    total_ing = 0.0
    total_gas = 0.0
    count = 0
    for m in re.finditer(r'\[TX:(\{[^\[\]]*?\})\]', combined_text):
        try:
            tx = json.loads(m.group(1).replace('\n', ' '))
            monto = float(tx.get('monto', 0))
            if tx.get('tipo') == 'INGRESO':
                total_ing += monto
            else:
                total_gas += monto
            count += 1
        except:
            pass
    return total_ing, total_gas, count


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/process-pdf", methods=["POST"])
def process_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    file_bytes = request.files["file"].read()

    try:
        text = extract_pdf_text(file_bytes)

        if not text or len(text.strip()) < 50:
            return jsonify({"error": "No se pudo extraer texto del PDF."}), 400

        bank_summary = extract_bank_summary(text)
        chunks = chunk_text(text, max_chars=14000)
        tolerance = 0.10

        # ── Paso 1: Haiku clasifica todo ──
        results = []
        for i, chunk in enumerate(chunks):
            part = "primera parte" if i == 0 else f"parte {i+1} de {len(chunks)}"
            prompt = f"""Clasifica TODAS las transacciones de esta {part} del estado de cuenta.
USA LOS MONTOS EXACTOS como aparecen. SOLO transacciones explicitas en el texto. NO inventes nada.

{chunk}"""
            results.append(call_anthropic_text(prompt, model="claude-haiku-4-5-20251001"))
        combined = "\n".join(results)
        tx_ing, tx_gas, tx_count = parse_tx_totals(combined)

        # ── Paso 2: Verificar contra resumen del banco ──
        disc_ing = bank_summary.get("deposits") and abs(tx_ing - bank_summary["deposits"]) > tolerance
        disc_gas = bank_summary.get("withdrawals") and abs(tx_gas - bank_summary["withdrawals"]) > tolerance
        rescued = 0

        # ── Paso 3: Si hay discrepancia, buscar solo lo que falta ──
        if disc_ing or disc_gas:
            missing_parts = []

            if disc_ing and bank_summary.get("deposits"):
                diff_ing = bank_summary["deposits"] - tx_ing
                if diff_ing > 0:
                    missing_parts.append(
                        f"Faltan INGRESOS por ${diff_ing:,.2f} en total. "
                        f"Busca en el estado de cuenta depósitos o pagos recibidos que sumen exactamente ${diff_ing:,.2f} "
                        f"y que NO hayan sido clasificados aún."
                    )

            if disc_gas and bank_summary.get("withdrawals"):
                diff_gas = bank_summary["withdrawals"] - tx_gas
                if diff_gas > 0:
                    missing_parts.append(
                        f"Faltan GASTOS por ${diff_gas:,.2f} en total. "
                        f"Busca en el estado de cuenta pagos o retiros que sumen exactamente ${diff_gas:,.2f} "
                        f"y que NO hayan sido clasificados aún."
                    )

            if missing_parts:
                # Already classified amounts to avoid duplicates
                import json as _json
                classified_amounts = []
                for m in re.finditer(r'\[TX:(\{[^\[\]]*?\})\]', combined):
                    try:
                        tx = _json.loads(m.group(1).replace('\n', ' '))
                        classified_amounts.append(round(float(tx.get('monto', 0)), 2))
                    except:
                        pass

                rescue_prompt = f"""Revisa este estado de cuenta y encuentra SOLO las transacciones que faltan.

{chr(10).join(missing_parts)}

IMPORTANTE:
- NO repitas transacciones que ya estén clasificadas
- Los montos ya clasificados son: {sorted(set(classified_amounts))}
- Busca transacciones con montos que NO estén en esa lista
- USA LOS MONTOS EXACTOS del documento

Estado de cuenta completo:
{text[:8000]}"""

                rescue_result = call_anthropic_text(rescue_prompt, model="claude-haiku-4-5-20251001")

                # Only add TXs that have NEW amounts (not already classified)
                import json as _json2
                new_txs = []
                remaining_amounts = classified_amounts.copy()
                for m in re.finditer(r'\[TX:(\{[^\[\]]*?\})\]', rescue_result):
                    try:
                        tx = _json2.loads(m.group(1).replace('\n', ' '))
                        monto = round(float(tx.get('monto', 0)), 2)
                        # Only add if this amount is not already classified
                        already_used = False
                        for i, ca in enumerate(remaining_amounts):
                            if abs(ca - monto) <= 0.02:
                                remaining_amounts.pop(i)
                                already_used = True
                                break
                        if not already_used:
                            new_txs.append(m.group(0))
                            rescued += 1
                    except:
                        pass

                if new_txs:
                    combined = combined + "\n" + "\n".join(new_txs)
                    tx_ing, tx_gas, tx_count = parse_tx_totals(combined)

        # ── Paso 4: Resultado final ──
        verification = {
            "tx_count": tx_count,
            "tx_ingresos": round(tx_ing, 2),
            "tx_gastos": round(tx_gas, 2),
            "bank_deposits": bank_summary.get("deposits"),
            "bank_withdrawals": bank_summary.get("withdrawals"),
            "ok": True,
            "warnings": [],
            "rescued": rescued
        }

        if bank_summary.get("deposits"):
            diff = abs(tx_ing - bank_summary["deposits"])
            if diff > tolerance:
                verification["ok"] = False
                verification["warnings"].append(
                    f"⚠️ Ingresos: ${tx_ing:,.2f} vs banco ${bank_summary['deposits']:,.2f} (diferencia ${diff:,.2f})"
                )

        if bank_summary.get("withdrawals"):
            diff = abs(tx_gas - bank_summary["withdrawals"])
            if diff > tolerance:
                verification["ok"] = False
                verification["warnings"].append(
                    f"⚠️ Gastos: ${tx_gas:,.2f} vs banco ${bank_summary['withdrawals']:,.2f} (diferencia ${diff:,.2f})"
                )

        return jsonify({
            "result": combined,
            "verification": verification
        })

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
