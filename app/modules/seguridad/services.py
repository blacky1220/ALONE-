import base64
import io
import secrets

import qrcode


def generar_codigo() -> str:
    return secrets.token_urlsafe(12)


def generar_qr_png_base64(data: str) -> str:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
