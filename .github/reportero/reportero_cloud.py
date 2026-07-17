# -*- coding: utf-8 -*-
"""
reportero_cloud.py - Reporte de failstop a Telegram, pensado para correr en GitHub Actions.

Diferencias con la version local:
  - No usa el CLI `gh`. Habla directo con la API de GitHub via urllib.
  - Toda la config viene de VARIABLES DE ENTORNO (los "secretos" del repo), nunca de un .env.
      TELEGRAM_BOT_TOKEN  (secreto)  -> token del bot
      TELEGRAM_CHAT_ID    (secreto)  -> a quien mandar
      GH_API_TOKEN        (lo pasa el propio workflow: ${{ github.token }})
  - El estado (estado.json) se guarda/restaura con el cache de Actions. Si no hay, no muestra
    variacion; el reporte igual sale. Nunca depende de que el estado exista.

Todo es best-effort: si una fuente falla, esa linea dice "(sin dato)" y el resto se manda igual.
Un reporte que no sale no sirve; preferimos uno incompleto antes que ninguno.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = "vectaosporley/failstop"
CAFECITO_URL = "https://cafecito.app/vecta"
ESTADO = Path(__file__).with_name("estado.json")   # lo restaura/guarda el cache de Actions
API = "https://api.github.com"


def _get_json(url: str, token: str | None = None, timeout: int = 20):
    """GET a una API JSON. Devuelve (data, None) o (None, motivo). Nunca lanza."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "failstop-reportero",
        "Accept": "application/vnd.github+json",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, type(e).__name__


def stats_github(token: str | None) -> dict:
    s = {"estrellas": None, "forks": None, "vistas": None, "clones": None}
    # estrellas / forks: publico, el token solo evita el limite de rate anonimo
    repo, _ = _get_json(f"{API}/repos/{REPO}", token)
    if repo:
        s["estrellas"] = repo.get("stargazers_count")
        s["forks"] = repo.get("forks_count")
    # vistas / clones: la API de trafico pide permiso de administracion sobre el repo.
    # Con el github.token del workflow + permissions: administration:read suele andar;
    # si no, queda "(sin dato)" y el reporte igual sale.
    tv, _ = _get_json(f"{API}/repos/{REPO}/traffic/views", token)
    if tv:
        s["vistas"] = tv.get("count")
    tc, _ = _get_json(f"{API}/repos/{REPO}/traffic/clones", token)
    if tc:
        s["clones"] = tc.get("count")
    return s


def cafecitos() -> int | None:
    """Lee la pagina publica de Cafecito y saca 'N recibidos'. None si no se puede.

    Cafecito intercala comentarios HTML entre el numero y la palabra:
      0<!-- --> recibidos . Por eso toleramos esa basura del medio.
    """
    try:
        req = urllib.request.Request(CAFECITO_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", errors="replace")
        m = re.search(r"(\d+)\s*(?:<!--.*?-->\s*)*recibidos", html, re.S)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def cargar_estado() -> dict:
    if ESTADO.is_file():
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def guardar_estado(d: dict):
    try:
        ESTADO.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def delta(hoy, ayer) -> str:
    if hoy is None or ayer is None:
        return ""
    d = hoy - ayer
    if d > 0:
        return f" (+{d})"
    if d < 0:
        return f" ({d})"
    return ""


def enviar_telegram(token: str, chat_id: str, texto: str) -> bool:
    if not token or not chat_id:
        print("falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el entorno")
        return False
    try:
        payload = urllib.parse.urlencode({
            "chat_id": chat_id, "text": texto, "disable_web_page_preview": "true",
        }).encode()
        with urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage", data=payload, timeout=20) as r:
            return json.load(r).get("ok", False)
    except Exception as e:
        print("error enviando a Telegram:", type(e).__name__, e)
        return False


def main() -> int:
    tok_tg = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    tok_gh = os.environ.get("GH_API_TOKEN") or os.environ.get("GITHUB_TOKEN") or None

    prev = cargar_estado()
    gh = stats_github(tok_gh)
    caf = cafecitos()
    hoy = {**gh, "cafecitos": caf, "ts": datetime.utcnow().isoformat(timespec="minutes") + "Z"}

    def linea(icono, nombre, clave):
        val = hoy.get(clave)
        if val is None:
            return f"{icono} {nombre}: (sin dato)"
        return f"{icono} {nombre}: {val}{delta(val, prev.get(clave))}"

    partes = [
        "failstop - reporte",
        linea("*", "estrellas", "estrellas"),
        linea(">", "forks", "forks"),
        linea("o", "vistas (14d)", "vistas"),
        linea("v", "clones (14d)", "clones"),
        linea("$", "cafecitos", "cafecitos"),
        "",
        "github.com/" + REPO,
    ]
    cambio = any(delta(hoy.get(k), prev.get(k)) for k in
                 ("estrellas", "forks", "vistas", "clones", "cafecitos"))
    if prev and not cambio:
        partes.insert(1, "(sin cambios desde el ultimo reporte)")

    texto = "\n".join(partes)
    ok = enviar_telegram(tok_tg, chat, texto)
    print("enviado:", "OK" if ok else "FALLO")
    print(texto)

    guardar_estado(hoy)
    # No fallamos el workflow por un envio fallido: dejamos el log y seguimos.
    return 0


if __name__ == "__main__":
    sys.exit(main())
