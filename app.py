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
- Tarjeta de crédito = L27a"""


def call_anthropic(messages,
