from typing import Optional
from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str


class ProjectInfo(BaseModel):
    name: str
    modified: str
    created: Optional[str] = None
    description: Optional[str] = None


class FileInfo(BaseModel):
    path: str
    name: str
    ext: str
    size: int


class FileContent(BaseModel):
    content: str


class RenameRequest(BaseModel):
    new_name: str


class ParseHtmlRequest(BaseModel):
    html: str = ""


class ParseCssRequest(BaseModel):
    css: str = ""


class ParseJsRequest(BaseModel):
    js: str = ""


class AddElementRequest(BaseModel):
    html: str = ""
    parent: str = "body"
    tag: str = "div"
    attrs: dict = {}
    content: str = ""


class RemoveElementRequest(BaseModel):
    html: str
    selector: str


class UpdateElementRequest(BaseModel):
    html: str
    selector: str
    attrs: Optional[dict] = None
    content: Optional[str] = None
