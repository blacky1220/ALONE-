"""Lector de estados de cuenta bancarios en PDF, Excel (.xlsx, .xls) y CSV.

Extrae los movimientos (fecha, descripción, monto, ABONO/CARGO) de archivos bancarios.
Soporta formatos estándar de banca en línea (PDF seleccionable, reportes Excel y CSV).
Detecta y sugiere automáticamente el departamento correspondiente analizando:
1. Referencia o identificador de unidad en el concepto (ej. A-101, Depto 102).
2. Nombre del propietario o residente en la descripción de la transferencia.
3. Importe exacto de adeudo pendiente o cuota de mantenimiento.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

# ── Fechas ──────────────────────────────────────────────────────────────────
_MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}

# 05/ENE/2026, 05-ENE-26, 05 ENE 2026, 5/ene/26
_FECHA_TEXTO = re.compile(
    r"^\s*(\d{1,2})[\s/\-]([A-Za-zÁÉÍÓÚáéíóú]{3,4})[\s/\-](\d{2,4})", re.UNICODE
)
# 05/01/2026, 05-01-26, 05/01/26
_FECHA_NUM = re.compile(r"^\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})")
# 2026-08-03 (ISO)
_FECHA_ISO = re.compile(r"^\s*(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})")

# Importe con centavos obligatorios: 1,234.56  ·  1234.56  ·  $2,500.00  ·  -300.00  ·  (150.00)
_MONTO = re.compile(r"\(?-?\$?\s?\d{1,3}(?:[,\s]\d{3})*\.\d{2}\)?|\(?-?\$?\s?\d+\.\d{2}\)?")

# Renglones que traen fecha e importe pero NO son movimientos (saldos de corte).
_NO_MOVIMIENTO = (
    "saldo inicial", "saldo anterior", "saldo final", "saldo al corte",
    "saldo promedio", "saldo disponible", "saldo del periodo", "saldo actual",
    "total abonos", "total cargos", "total depositos", "total retiros",
)

_ABONO_KEYS = (
    "abono", "deposito", "depósito", "spei recibido", "recibido", "credito",
    "crédito", "pago recibido", "transferencia recibida", "traspaso recibido",
    "abonos", "depósitos", "ingreso", "ingresos", "entrada", "entradas",
)
_CARGO_KEYS = (
    "cargo", "retiro", "comision", "comisión", "iva", "pago", "compra",
    "spei enviado", "enviado", "domiciliacion", "domiciliación", "debito", "débito",
    "traspaso enviado", "disposicion", "disposición", "egreso", "egresos", "salida",
)


def _norm_anio(a: str) -> int:
    n = int(a)
    return n if n >= 100 else 2000 + n


def _parse_fecha(linea: str, anio_defecto: int | None = None) -> date | None:
    if isinstance(linea, (date, datetime)):
        return linea if isinstance(linea, date) and not isinstance(linea, datetime) else linea.date()
    val = str(linea or "").strip()
    m_iso = _FECHA_ISO.match(val)
    if m_iso:
        anio, mes, dia = m_iso.groups()
        try:
            return date(int(anio), int(mes), int(dia))
        except ValueError:
            pass
    m = _FECHA_TEXTO.match(val)
    if m:
        dia, mes_txt, anio = m.groups()
        mes = _MESES.get(mes_txt[:3].lower())
        if mes:
            try:
                return date(_norm_anio(anio), mes, int(dia))
            except ValueError:
                pass
    m = _FECHA_NUM.match(val)
    if m:
        dia, mes, anio = m.groups()
        try:
            return date(_norm_anio(anio), int(mes), int(dia))
        except ValueError:
            pass
    return None


def _to_decimal(token: Any) -> Decimal | None:
    if token is None or token == "":
        return None
    if isinstance(token, (int, float, Decimal)):
        try:
            return Decimal(str(token)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None
    token_str = str(token).strip()
    neg = token_str.startswith("(") or token_str.startswith("-")
    limpio = re.sub(r"[^\d.]", "", token_str)
    if not limpio:
        return None
    try:
        val = Decimal(limpio).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -val if neg else val


def _clasificar(concepto: str) -> str | None:
    """ABONO/CARGO por palabras clave; None si no hay señal clara."""
    c = concepto.lower()
    abono = any(k in c for k in _ABONO_KEYS)
    cargo = any(k in c for k in _CARGO_KEYS)
    if abono and not cargo:
        return "ABONO"
    if cargo and not abono:
        return "CARGO"
    return None


# ── Lector Excel (.xlsx / .xls) ─────────────────────────────────────────────

def parse_excel_statement(file_bytes: bytes) -> dict:
    """Lee movimientos bancarios desde un archivo Excel (openpyxl)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet = wb.active

    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return {"movimientos": [], "texto_crudo": "", "paginas": 1, "aviso": "El archivo Excel está vacío."}

    # Buscar la fila de encabezados
    header_idx = -1
    col_map: dict[str, int] = {}

    for idx, r in enumerate(rows[:15]):  # buscar encabezado en las primeras 15 filas
        row_strs = [str(cell or "").strip().lower() for cell in r]
        # Verificar si parece encabezado bancario
        has_fecha = any("fecha" in c or "date" in c for c in row_strs)
        has_concepto = any(any(k in c for k in ("concepto", "descrip", "detalle", "movimiento", "referencia")) for c in row_strs)
        has_monto = any(any(k in c for k in ("monto", "importe", "abono", "deposito", "cargo", "retiro")) for c in row_strs)

        if has_fecha and (has_concepto or has_monto):
            header_idx = idx
            for c_idx, c in enumerate(row_strs):
                if not c:
                    continue
                if "fecha" in c or "date" in c:
                    col_map.setdefault("fecha", c_idx)
                elif any(k in c for k in ("concepto", "descrip", "detalle", "movimiento", "referencia")):
                    col_map.setdefault("concepto", c_idx)
                elif any(k in c for k in ("abono", "deposito", "depósito", "credito", "crédito", "haber")):
                    col_map.setdefault("abono", c_idx)
                elif any(k in c for k in ("cargo", "retiro", "debito", "débito", "debe")):
                    col_map.setdefault("cargo", c_idx)
                elif any(k in c for k in ("monto", "importe", "valor")):
                    col_map.setdefault("monto", c_idx)
                elif "saldo" in c or "balance" in c:
                    col_map.setdefault("saldo", c_idx)
                elif "tipo" in c:
                    col_map.setdefault("tipo", c_idx)
                elif any(k in c for k in ("unidad", "depto", "departamento")):
                    col_map.setdefault("unidad", c_idx)
            break

    movimientos: list[dict] = []
    texto_resumen_lineas: list[str] = []

    start_row = header_idx + 1 if header_idx >= 0 else 0
    for r in rows[start_row:]:
        if not r or all(c is None or str(c).strip() == "" for c in r):
            continue

        raw_line = " | ".join(str(c) for c in r if c is not None)

        # Extraer fecha
        fecha = None
        if "fecha" in col_map and col_map["fecha"] < len(r):
            fecha = _parse_fecha(r[col_map["fecha"]])
        else:
            for cell in r:
                f_try = _parse_fecha(cell)
                if f_try:
                    fecha = f_try
                    break

        if not fecha:
            continue

        # Extraer concepto
        concepto = ""
        if "concepto" in col_map and col_map["concepto"] < len(r):
            concepto = str(r[col_map["concepto"]] or "").strip()
        else:
            # Buscar texto largo
            textos = [str(c).strip() for c in r if isinstance(c, str) and len(str(c).strip()) > 3]
            concepto = textos[0] if textos else "(sin descripción)"

        # Omitir filas de totales o saldos
        if any(k in concepto.lower() for k in _NO_MOVIMIENTO):
            continue

        # Extraer monto y tipo
        monto: Decimal | None = None
        tipo: str = "ABONO"
        saldo: Decimal | None = None

        if "saldo" in col_map and col_map["saldo"] < len(r):
            saldo = _to_decimal(r[col_map["saldo"]])

        # Caso 1: Columnas separadas de Abono y Cargo
        abono_val = _to_decimal(r[col_map["abono"]]) if "abono" in col_map and col_map["abono"] < len(r) else None
        cargo_val = _to_decimal(r[col_map["cargo"]]) if "cargo" in col_map and col_map["cargo"] < len(r) else None

        if abono_val is not None and abono_val > 0:
            monto = abono_val
            tipo = "ABONO"
        elif cargo_val is not None and cargo_val > 0:
            monto = cargo_val
            tipo = "CARGO"
        elif "monto" in col_map and col_map["monto"] < len(r):
            monto_val = _to_decimal(r[col_map["monto"]])
            if monto_val is not None:
                if monto_val < 0:
                    monto = abs(monto_val)
                    tipo = "CARGO"
                else:
                    monto = monto_val
                    # Checar columna tipo si existe
                    if "tipo" in col_map and col_map["tipo"] < len(r):
                        t_str = str(r[col_map["tipo"]] or "").strip().upper()
                        tipo = "CARGO" if "CARGO" in t_str or "RETIRO" in t_str else "ABONO"
                    else:
                        tipo_clasif = _clasificar(concepto)
                        tipo = tipo_clasif or "ABONO"

        if monto is None or monto <= 0:
            # Intentar encontrar número en celdas
            for cell in r:
                d = _to_decimal(cell)
                if d is not None and d != 0 and d != saldo:
                    monto = abs(d)
                    tipo = "CARGO" if d < 0 else (_clasificar(concepto) or "ABONO")
                    break

        if monto is None or monto <= 0:
            continue

        texto_resumen_lineas.append(f"{fecha} | {concepto} | {tipo} | ${monto:.2f}")
        movimientos.append({
            "fecha": fecha,
            "descripcion": concepto[:255] or "(sin descripción)",
            "monto": monto,
            "tipo": tipo,
            "saldo": saldo,
        })

    aviso = None
    if not movimientos:
        aviso = "Se procesó el archivo Excel pero no se reconocieron movimientos con columnas válidas de fecha e importe."

    return {
        "movimientos": movimientos,
        "texto_crudo": "\n".join(texto_resumen_lineas),
        "paginas": 1,
        "aviso": aviso,
    }


# ── Lector CSV ──────────────────────────────────────────────────────────────

def parse_csv_statement(file_bytes: bytes) -> dict:
    """Lee movimientos bancarios desde un archivo CSV con autodetección de delimitador."""
    # Probar decodificaciones comunes
    texto = ""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            texto = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if not texto.strip():
        return {"movimientos": [], "texto_crudo": "", "paginas": 1, "aviso": "El archivo CSV está vacío o ilegible."}

    # Detectar delimitador
    primera_linea = texto.splitlines()[0] if texto.splitlines() else ""
    delim = ","
    for d in (",", ";", "\t", "|"):
        if primera_linea.count(d) > primera_linea.count(delim):
            delim = d

    reader = csv.reader(io.StringIO(texto), delimiter=delim)
    rows = list(reader)

    # Reutilizar lógica de filas idéntica a Excel
    # Creamos un mock workbook con rows
    header_idx = -1
    col_map: dict[str, int] = {}

    for idx, r in enumerate(rows[:15]):
        row_strs = [str(cell or "").strip().lower() for cell in r]
        has_fecha = any("fecha" in c or "date" in c for c in row_strs)
        has_concepto = any(any(k in c for k in ("concepto", "descrip", "detalle", "movimiento", "referencia")) for c in row_strs)
        has_monto = any(any(k in c for k in ("monto", "importe", "abono", "deposito", "cargo", "retiro")) for c in row_strs)

        if has_fecha and (has_concepto or has_monto):
            header_idx = idx
            for c_idx, c in enumerate(row_strs):
                if not c:
                    continue
                if "fecha" in c or "date" in c:
                    col_map.setdefault("fecha", c_idx)
                elif any(k in c for k in ("concepto", "descrip", "detalle", "movimiento", "referencia")):
                    col_map.setdefault("concepto", c_idx)
                elif any(k in c for k in ("abono", "deposito", "depósito", "credito", "crédito", "haber")):
                    col_map.setdefault("abono", c_idx)
                elif any(k in c for k in ("cargo", "retiro", "debito", "débito", "debe")):
                    col_map.setdefault("cargo", c_idx)
                elif any(k in c for k in ("monto", "importe", "valor")):
                    col_map.setdefault("monto", c_idx)
                elif "saldo" in c or "balance" in c:
                    col_map.setdefault("saldo", c_idx)
                elif "tipo" in c:
                    col_map.setdefault("tipo", c_idx)
            break

    movimientos: list[dict] = []
    texto_resumen_lineas: list[str] = []
    start_row = header_idx + 1 if header_idx >= 0 else 0

    for r in rows[start_row:]:
        if not r or all(str(c).strip() == "" for c in r):
            continue
        fecha = None
        if "fecha" in col_map and col_map["fecha"] < len(r):
            fecha = _parse_fecha(r[col_map["fecha"]])
        else:
            for cell in r:
                f_try = _parse_fecha(cell)
                if f_try:
                    fecha = f_try
                    break
        if not fecha:
            continue

        concepto = ""
        if "concepto" in col_map and col_map["concepto"] < len(r):
            concepto = str(r[col_map["concepto"]] or "").strip()
        else:
            textos = [str(c).strip() for c in r if len(str(c).strip()) > 3]
            concepto = textos[0] if textos else "(sin descripción)"

        if any(k in concepto.lower() for k in _NO_MOVIMIENTO):
            continue

        monto: Decimal | None = None
        tipo = "ABONO"
        saldo: Decimal | None = None
        if "saldo" in col_map and col_map["saldo"] < len(r):
            saldo = _to_decimal(r[col_map["saldo"]])

        abono_val = _to_decimal(r[col_map["abono"]]) if "abono" in col_map and col_map["abono"] < len(r) else None
        cargo_val = _to_decimal(r[col_map["cargo"]]) if "cargo" in col_map and col_map["cargo"] < len(r) else None

        if abono_val is not None and abono_val > 0:
            monto = abono_val
            tipo = "ABONO"
        elif cargo_val is not None and cargo_val > 0:
            monto = cargo_val
            tipo = "CARGO"
        elif "monto" in col_map and col_map["monto"] < len(r):
            monto_val = _to_decimal(r[col_map["monto"]])
            if monto_val is not None:
                if monto_val < 0:
                    monto = abs(monto_val)
                    tipo = "CARGO"
                else:
                    monto = monto_val
                    tipo = _clasificar(concepto) or "ABONO"

        if monto is None or monto <= 0:
            continue

        texto_resumen_lineas.append(f"{fecha} | {concepto} | {tipo} | ${monto:.2f}")
        movimientos.append({
            "fecha": fecha,
            "descripcion": concepto[:255] or "(sin descripción)",
            "monto": monto,
            "tipo": tipo,
            "saldo": saldo,
        })

    aviso = None if movimientos else "No se detectaron movimientos con formato reconocible en el CSV."
    return {
        "movimientos": movimientos,
        "texto_crudo": "\n".join(texto_resumen_lineas),
        "paginas": 1,
        "aviso": aviso,
    }


# ── Lector PDF ──────────────────────────────────────────────────────────────

def parse_pdf_statement(pdf_bytes: bytes, anio_defecto: int | None = None) -> dict:
    """Extrae movimientos de un PDF de banca en línea (con capa de texto)."""
    texto_paginas: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        n_paginas = len(pdf.pages)
        for page in pdf.pages:
            txt = page.extract_text(layout=True, x_tolerance=1.5) or ""
            texto_paginas.append(txt)

    texto_crudo = "\n".join(texto_paginas)

    if not texto_crudo.strip():
        return {
            "movimientos": [], "texto_crudo": "", "paginas": n_paginas,
            "aviso": ("No se pudo extraer texto del PDF. Probablemente es un estado de "
                      "cuenta escaneado (imagen). Sube un PDF descargado de banca en línea "
                      "o un archivo en Excel (.xlsx) / CSV."),
        }

    movimientos: list[dict] = []
    saldo_previo: Decimal | None = None

    for linea in texto_crudo.splitlines():
        fecha = _parse_fecha(linea, anio_defecto)
        if not fecha:
            continue
        tokens = _MONTO.findall(linea)
        if not tokens:
            continue
        importes = [d for d in (_to_decimal(t) for t in tokens) if d is not None]
        if not importes:
            continue

        if len(importes) >= 2:
            saldo = importes[-1]
            monto_mov = importes[-2]
        else:
            saldo = None
            monto_mov = importes[-1]

        concepto = linea.strip()
        concepto = re.sub(r"^\s*\S+\s*", "", concepto) if _FECHA_NUM.match(linea) else concepto
        m = _FECHA_TEXTO.match(linea) or _FECHA_NUM.match(linea) or _FECHA_ISO.match(linea)
        if m:
            concepto = linea[m.end():]
        for t in tokens:
            concepto = concepto.replace(t, " ")
        concepto = re.sub(r"\s{2,}", " ", concepto).strip(" .-|")

        if any(k in concepto.lower() for k in _NO_MOVIMIENTO):
            if len(importes) >= 1:
                saldo_previo = importes[-1]
            continue

        tipo = _clasificar(concepto)
        if tipo is None and saldo is not None and saldo_previo is not None:
            tipo = "ABONO" if saldo > saldo_previo else "CARGO"
        if tipo is None:
            tipo = "CARGO" if monto_mov < 0 else "ABONO"

        if saldo is not None:
            saldo_previo = saldo

        movimientos.append({
            "fecha": fecha,
            "descripcion": concepto[:255] or "(sin descripción)",
            "monto": abs(monto_mov),
            "tipo": tipo,
            "saldo": saldo,
        })

    aviso = None
    if not movimientos:
        aviso = ("Se leyó el texto del PDF pero no se reconocieron movimientos con el "
                 "formato esperado (fecha + importe con centavos). Puedes revisar el texto "
                 "extraído o cargar el archivo en formato Excel.")

    return {
        "movimientos": movimientos,
        "texto_crudo": texto_crudo,
        "paginas": n_paginas,
        "aviso": aviso,
    }


# ── Entrada Principal Polivalente ──────────────────────────────────────────

def parse_bank_statement(
    contenido_bytes: bytes,
    nombre_archivo: str = "",
    anio_defecto: int | None = None,
) -> dict:
    """Punto de entrada universal. Autodetecta el tipo de archivo (PDF, Excel, CSV)
    por extensión o por encabezado de bytes y delega al extractor correspondiente."""
    nombre_lower = (nombre_archivo or "").lower()

    if nombre_lower.endswith((".xlsx", ".xls")) or contenido_bytes[:4] == b"PK\x03\x04":
        return parse_excel_statement(contenido_bytes)

    if nombre_lower.endswith(".csv"):
        return parse_csv_statement(contenido_bytes)

    if nombre_lower.endswith(".pdf") or contenido_bytes[:4] == b"%PDF":
        return parse_pdf_statement(contenido_bytes, anio_defecto)

    # Por defecto intentar como PDF; si falla, intentar como Excel o CSV
    try:
        if b"%PDF" in contenido_bytes[:1024]:
            return parse_pdf_statement(contenido_bytes, anio_defecto)
        elif b"PK\x03\x04" in contenido_bytes[:1024]:
            return parse_excel_statement(contenido_bytes)
        else:
            return parse_csv_statement(contenido_bytes)
    except Exception:
        return parse_pdf_statement(contenido_bytes, anio_defecto)


# ── Emparejamiento Inteligente con Departamentos ────────────────────────────

def _normalizar(s: str) -> str:
    """Elimina acentos, puntuación y espacios para comparación flexible."""
    if not s:
        return ""
    s = s.lower()
    reemplazos = (
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
        ("ä", "a"), ("ë", "e"), ("ï", "i"), ("ö", "o"), ("ü", "u"),
        ("ñ", "n"),
    )
    for orig, rep in reemplazos:
        s = s.replace(orig, rep)
    return re.sub(r"[\s\-_.,/\\#]", "", s)


def sugerir_unidad(
    descripcion: str,
    monto: Decimal,
    unidades: list,
    propietarios_por_unidad: dict[int, str] | None = None,
    cuotas_por_unidad: dict[int, Decimal] | None = None,
) -> tuple[int | None, str]:
    """Sugiere a qué departamento pertenece un abono. Devuelve (unidad_id, confianza).

    Nivel de confianza:
    - 'referencia': Encontró el identificador del departamento en el concepto (ej. A-101, Depto 102).
    - 'propietario': Encontró el nombre o apellido del propietario/residente en el concepto.
    - 'monto': Una sola unidad tiene un adeudo pendiente que coincide con el importe exacto.
    - 'cuota': Una sola unidad tiene una cuota mensual fija idéntica al importe.
    - 'ninguno': No se pudo asociar de forma automática, requiere selección manual.
    """
    desc_norm = _normalizar(descripcion)
    if not desc_norm:
        return None, "ninguno"

    # 1. Emparejamiento por identificador de unidad (el más específico primero)
    # ej. "A-101", "101", "Depto 102"
    for u in sorted(unidades, key=lambda x: len(x.identificador), reverse=True):
        ident = _normalizar(u.identificador)
        if ident and len(ident) >= 2:
            if ident in desc_norm:
                return u.id, "referencia"
            # Probar variantes como "depto101", "d101", "torre101"
            for prefix in ("depto", "dto", "dept", "dep", "d", "torre", "casa"):
                if f"{prefix}{ident}" in desc_norm:
                    return u.id, "referencia"

    # 2. Emparejamiento por nombre del propietario / residente
    if propietarios_por_unidad:
        for u_id, nombre_completo in propietarios_por_unidad.items():
            if not nombre_completo:
                continue
            nom_norm = _normalizar(nombre_completo)
            # Si el nombre completo normalizado aparece en el concepto
            if len(nom_norm) >= 6 and nom_norm in desc_norm:
                return u_id, "propietario"

            # O si al menos dos partes del nombre (ej. Nombre + Apellido) aparecen
            partes = [p.strip() for p in re.split(r"\s+", nombre_completo) if len(p.strip()) >= 4]
            if len(partes) >= 2:
                coincidencias = sum(1 for p in partes if _normalizar(p) in desc_norm)
                if coincidencias >= 2:
                    return u_id, "propietario"

    # 3. Emparejamiento por cuota mensual de mantenimiento
    if cuotas_por_unidad and monto and monto > 0:
        unidades_con_cuota = [uid for uid, c_monto in cuotas_por_unidad.items() if c_monto == monto]
        if len(unidades_con_cuota) == 1:
            return unidades_con_cuota[0], "cuota"

    return None, "ninguno"

