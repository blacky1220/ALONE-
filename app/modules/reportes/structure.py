"""Estructura web — utilidades para manipular HTML desde el servidor."""

from bs4 import BeautifulSoup


def add_element(html: str, parent_selector: str, tag: str,
                attrs: dict | None = None, content: str = "") -> str:
    soup  = BeautifulSoup(html, "html.parser")
    attrs = attrs or {}

    parent = (
        soup.find(id=parent_selector.lstrip("#"))
        if parent_selector.startswith("#")
        else soup.select_one(parent_selector)
    )
    if parent is None:
        raise ValueError(f"Elemento padre '{parent_selector}' no encontrado.")

    new_tag = soup.new_tag(tag, **attrs)
    if content:
        new_tag.string = content
    parent.append(new_tag)
    return str(soup)


def remove_element(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    el   = soup.select_one(selector)
    if el is None:
        raise ValueError(f"Elemento '{selector}' no encontrado.")
    el.decompose()
    return str(soup)


def update_element(html: str, selector: str,
                   attrs: dict | None = None, content: str | None = None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    el   = soup.select_one(selector)
    if el is None:
        raise ValueError(f"Elemento '{selector}' no encontrado.")
    if attrs:
        for k, v in attrs.items():
            el[k] = v
    if content is not None:
        el.clear()
        el.append(BeautifulSoup(content, "html.parser"))
    return str(soup)


def move_element(html: str, selector: str, new_parent_selector: str) -> str:
    soup       = BeautifulSoup(html, "html.parser")
    el         = soup.select_one(selector)
    new_parent = soup.select_one(new_parent_selector)
    if el is None or new_parent is None:
        raise ValueError("Selector de origen o destino no encontrado.")
    el.extract()
    new_parent.append(el)
    return str(soup)


def get_element_styles(html: str, selector: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    el   = soup.select_one(selector)
    if el is None:
        return {}
    style_str = el.get("style", "")
    styles: dict[str, str] = {}
    for rule in style_str.split(";"):
        rule = rule.strip()
        if ":" in rule:
            k, _, v = rule.partition(":")
            styles[k.strip()] = v.strip()
    return styles
