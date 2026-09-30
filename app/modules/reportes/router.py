from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.core.dependencies import require_admin
from app.modules.auth.models import User
from app.modules.reportes import parser, services, structure
from app.modules.reportes.schemas import (
    AddElementRequest,
    FileContent,
    ParseCssRequest,
    ParseHtmlRequest,
    ParseJsRequest,
    ProjectCreate,
    RemoveElementRequest,
    RenameRequest,
    UpdateElementRequest,
)

router = APIRouter(
    prefix="/reportes",
    tags=["Reportes"],
    dependencies=[Depends(require_admin)],
)


# ── Proyectos ────────────────────────────────────────────────────────────────

@router.get("/projects")
def get_projects():
    return services.list_projects()


@router.post("/projects", status_code=201)
def new_project(data: ProjectCreate):
    name = data.name.strip()
    if not name:
        return _error("Nombre requerido", 400)
    try:
        return services.create_project(name)
    except FileExistsError as e:
        return _error(str(e), 409)


@router.delete("/projects/{name}")
def remove_project(name: str):
    try:
        services.delete_project(name)
        return {"deleted": True}
    except FileNotFoundError as e:
        return _error(str(e), 404)


# ── Archivos ─────────────────────────────────────────────────────────────────

@router.get("/projects/{project}/files")
def get_files(project: str):
    try:
        return services.list_project_files(project)
    except FileNotFoundError as e:
        return _error(str(e), 404)


@router.get("/projects/{project}/files/{filepath:path}")
def get_file(project: str, filepath: str):
    try:
        return {"content": services.read_file(project, filepath)}
    except FileNotFoundError as e:
        return _error(str(e), 404)


@router.put("/projects/{project}/files/{filepath:path}")
def save_file(project: str, filepath: str, data: FileContent):
    try:
        return services.write_file(project, filepath, data.content)
    except FileNotFoundError as e:
        return _error(str(e), 404)


@router.delete("/projects/{project}/files/{filepath:path}")
def remove_file(project: str, filepath: str):
    try:
        services.delete_file(project, filepath)
        return {"deleted": True}
    except FileNotFoundError as e:
        return _error(str(e), 404)


@router.post("/projects/{project}/files/{filepath:path}/rename")
def rename_file(project: str, filepath: str, data: RenameRequest):
    new_name = data.new_name.strip()
    if not new_name:
        return _error("Nuevo nombre requerido", 400)
    try:
        return services.rename_file(project, filepath, new_name)
    except FileNotFoundError as e:
        return _error(str(e), 404)


# ── Parser ───────────────────────────────────────────────────────────────────

@router.post("/parse/html")
def parse_html_route(data: ParseHtmlRequest):
    return parser.parse_html(data.html)


@router.post("/parse/css")
def parse_css_route(data: ParseCssRequest):
    return parser.parse_css(data.css)


@router.post("/parse/js")
def parse_js_route(data: ParseJsRequest):
    return parser.parse_js(data.js)


# ── Estructura ───────────────────────────────────────────────────────────────

@router.post("/structure/add")
def add_element(data: AddElementRequest):
    try:
        return {"html": structure.add_element(
            data.html, data.parent, data.tag, data.attrs, data.content
        )}
    except ValueError as e:
        return _error(str(e), 400)


@router.post("/structure/remove")
def remove_element(data: RemoveElementRequest):
    try:
        return {"html": structure.remove_element(data.html, data.selector)}
    except ValueError as e:
        return _error(str(e), 400)


@router.post("/structure/update")
def update_element(data: UpdateElementRequest):
    try:
        return {"html": structure.update_element(
            data.html, data.selector, data.attrs, data.content
        )}
    except ValueError as e:
        return _error(str(e), 400)


# ── Exportar ─────────────────────────────────────────────────────────────────

@router.get("/projects/{name}/export")
def export_project(name: str):
    try:
        zip_path = services.export_project(name)
        return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")
    except FileNotFoundError as e:
        return _error(str(e), 404)


# ── Health ───────────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {"status": "ok", "app": "reportes"}


def _error(message: str, status_code: int):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content={"error": message})
