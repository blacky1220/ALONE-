"""Núcleo del módulo de reportes — gestión de proyectos y archivos de reporte.

Portado desde sistema-VERSION1 (editor/core.py). Cada "proyecto" es una carpeta
de archivos HTML/CSS/JS que se puede editar y exportar como plantilla de reporte
para el condominio (estados de cuenta, avisos, etc.).
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent / "data"
PROJECTS_DIR = BASE_DIR / "projects"
EXPORTS_DIR = BASE_DIR / "exports"

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Proyectos ────────────────────────────────────────────────────────────────

def list_projects() -> list[dict]:
    projects = []
    for p in sorted(PROJECTS_DIR.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            meta_file = p / "meta.json"
            meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
            projects.append({
                "name": p.name,
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                **meta,
            })
    return projects


def create_project(name: str) -> dict:
    project_path = PROJECTS_DIR / name
    if project_path.exists():
        raise FileExistsError(f"El reporte '{name}' ya existe.")

    project_path.mkdir(parents=True)

    (project_path / "index.html").write_text(default_html(name), encoding="utf-8")
    (project_path / "styles.css").write_text(default_css(), encoding="utf-8")
    (project_path / "script.js").write_text(default_js(), encoding="utf-8")

    meta = {"created": datetime.now().isoformat(), "description": ""}
    (project_path / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return {"name": name, "files": list_project_files(name)}


def delete_project(name: str) -> None:
    project_path = PROJECTS_DIR / name
    if not project_path.exists():
        raise FileNotFoundError(f"Reporte '{name}' no encontrado.")
    shutil.rmtree(project_path)


# ── Archivos ─────────────────────────────────────────────────────────────────

def list_project_files(name: str) -> list[dict]:
    project_path = PROJECTS_DIR / name
    if not project_path.exists():
        raise FileNotFoundError(f"Reporte '{name}' no encontrado.")
    files = []
    for f in sorted(project_path.rglob("*")):
        if f.is_file() and f.name != "meta.json":
            rel = f.relative_to(project_path)
            files.append({
                "path": str(rel).replace("\\", "/"),
                "name": f.name,
                "ext": f.suffix.lstrip("."),
                "size": f.stat().st_size,
            })
    return files


def read_file(project: str, filepath: str) -> str:
    path = PROJECTS_DIR / project / filepath
    if not path.exists():
        raise FileNotFoundError(f"Archivo '{filepath}' no encontrado.")
    return path.read_text(encoding="utf-8")


def write_file(project: str, filepath: str, content: str) -> dict:
    project_path = PROJECTS_DIR / project
    if not project_path.exists():
        raise FileNotFoundError(f"Reporte '{project}' no encontrado.")
    path = project_path / filepath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"saved": True, "path": filepath, "size": path.stat().st_size}


def delete_file(project: str, filepath: str) -> None:
    path = PROJECTS_DIR / project / filepath
    if not path.exists():
        raise FileNotFoundError(f"Archivo '{filepath}' no encontrado.")
    path.unlink()


def rename_file(project: str, old: str, new: str) -> dict:
    old_path = PROJECTS_DIR / project / old
    new_path = PROJECTS_DIR / project / new
    if not old_path.exists():
        raise FileNotFoundError(f"Archivo '{old}' no encontrado.")
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.rename(new_path)
    return {"renamed": True, "from": old, "to": new}


# ── Exportar ─────────────────────────────────────────────────────────────────

def export_project(name: str) -> Path:
    project_path = PROJECTS_DIR / name
    if not project_path.exists():
        raise FileNotFoundError(f"Reporte '{name}' no encontrado.")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = EXPORTS_DIR / f"{name}_{timestamp}"
    shutil.make_archive(str(zip_path), "zip", str(project_path))
    return Path(str(zip_path) + ".zip")


# ── Plantillas por defecto ────────────────────────────────────────────────────

def default_html(name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{name}</title>
  <link rel="stylesheet" href="styles.css"/>
</head>
<body>
  <h1>{name}</h1>
  <p>Plantilla de reporte nueva.</p>
  <script src="script.js"></script>
</body>
</html>"""


def default_css() -> str:
    return """* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', sans-serif; padding: 2rem; }
"""


def default_js() -> str:
    return "// Script del reporte\nconsole.log('Reporte iniciado');\n"
