#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def run_kapso_templates_list(phone_number_id: str) -> dict:
    command = [
        "npx",
        "kapso",
        "whatsapp",
        "templates",
        "list",
        "--phone-number-id",
        phone_number_id,
        "--output",
        "json",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT / "kapso",
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "kapso CLI failed")

    lines = [line for line in completed.stdout.splitlines() if not line.lstrip().startswith("›")]
    payload = "\n".join(lines).strip()
    return json.loads(payload or "{}")


def main() -> int:
    load_env_file(ROOT / ".env")
    backend_base_url = os.environ.get("AGRO_BACKEND_VERIFY_BASE_URL") or DEFAULT_BACKEND_URL
    phone_number_id = os.environ.get("KAPSO_PHONE_NUMBER_ID", "").strip()
    expected_template = os.environ.get("KAPSO_NEW_LOAD_TEMPLATE_NAME", "").strip()

    print("== Verificacion fallback template WhatsApp/Kapso ==")
    print(f"Backend: {backend_base_url}")
    print(f"Phone number id: {phone_number_id or '(faltante)'}")
    print(f"Template esperado: {expected_template or '(faltante)'}")

    failed = False

    try:
        health = fetch_json(f"{backend_base_url}/health")
        print(f"[OK] /health -> {health}")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] No pude consultar /health: {exc}")
        return 1

    try:
        db_health = fetch_json(f"{backend_base_url}/health/db")
        print(f"[OK] /health/db -> {db_health}")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] No pude consultar /health/db: {exc}")
        failed = True

    try:
        whatsapp_health = fetch_json(f"{backend_base_url}/health/whatsapp")
        print(f"[OK] /health/whatsapp -> {whatsapp_health}")
        if expected_template and whatsapp_health.get("new_load_template_name") != expected_template:
            print("[ERROR] El backend no levanto el template esperado desde el .env.")
            failed = True
        if not whatsapp_health.get("new_load_template_configured"):
            print("[ERROR] El backend sigue sin template configurado para reabrir la ventana 24h.")
            failed = True
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] No pude consultar /health/whatsapp: {exc}")
        failed = True

    if not phone_number_id:
        print("[ERROR] Falta KAPSO_PHONE_NUMBER_ID en el .env.")
        return 1

    try:
        templates_payload = run_kapso_templates_list(phone_number_id)
        templates = templates_payload.get("data", [])
        matching_template = next((item for item in templates if item.get("name") == expected_template), None)
        if matching_template is None:
            print(f"[ERROR] Kapso no devuelve el template {expected_template!r} para este numero.")
            failed = True
        else:
            print(
                "[OK] Template Kapso -> "
                f"name={matching_template.get('name')} "
                f"status={matching_template.get('status')} "
                f"language={matching_template.get('language')}"
            )
            if matching_template.get("status") != "APPROVED":
                print("[WARN] El template existe pero todavia no esta APPROVED.")
                failed = True
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] No pude consultar templates en Kapso: {exc}")
        failed = True

    if failed:
        print("Resultado: verificacion incompleta o con bloqueos.")
        return 1

    print("Resultado: fallback listo para usar.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print(f"[ERROR] URL invalida o backend no accesible: {exc}")
        raise SystemExit(1) from exc
