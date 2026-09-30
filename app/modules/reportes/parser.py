"""Parser HTML/CSS/JS — analiza estructura y extrae metadatos."""

import re
from bs4 import BeautifulSoup


# ── HTML ─────────────────────────────────────────────────────────────────────

def parse_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    return {
        "title":    soup.title.string if soup.title else "",
        "elements": _count_elements(soup),
        "tree":     _build_tree(soup.body or soup),
        "links":    [a.get("href", "") for a in soup.find_all("a")],
        "images":   [i.get("src", "")  for i in soup.find_all("img")],
        "scripts":  [s.get("src", "")  for s in soup.find_all("script") if s.get("src")],
        "styles":   [l.get("href", "") for l in soup.find_all("link", rel="stylesheet")],
    }


def _count_elements(soup: BeautifulSoup) -> dict:
    tags = [t.name for t in soup.find_all() if t.name]
    counts: dict[str, int] = {}
    for tag in tags:
        counts[tag] = counts.get(tag, 0) + 1
    return counts


def _build_tree(node, depth: int = 0, max_depth: int = 6) -> dict | None:
    if depth > max_depth or not hasattr(node, "name") or not node.name:
        return None
    children = [
        c for child in node.children
        if (c := _build_tree(child, depth + 1, max_depth)) is not None
    ]
    return {
        "tag":      node.name,
        "id":       node.get("id", ""),
        "classes":  node.get("class", []),
        "children": children,
    }


# ── CSS ──────────────────────────────────────────────────────────────────────

def parse_css(css: str) -> dict:
    rules: list[dict] = []
    pattern = re.compile(r"([^{]+)\{([^}]*)\}", re.DOTALL)
    for match in pattern.finditer(css):
        selector = match.group(1).strip()
        props_raw = match.group(2).strip()
        props = {}
        for line in props_raw.splitlines():
            line = line.strip().rstrip(";")
            if ":" in line:
                k, _, v = line.partition(":")
                props[k.strip()] = v.strip()
        if selector:
            rules.append({"selector": selector, "properties": props})
    return {"rules": rules, "count": len(rules)}


# ── JS ───────────────────────────────────────────────────────────────────────

def parse_js(js: str) -> dict:
    functions = re.findall(r"function\s+(\w+)\s*\(", js)
    arrow_fns = re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:\([^)]*\)|[\w]+)\s*=>", js)
    classes   = re.findall(r"\bclass\s+(\w+)", js)
    imports   = re.findall(r'import\s+.*?\s+from\s+["\']([^"\']+)["\']', js)
    return {
        "functions": functions + arrow_fns,
        "classes":   classes,
        "imports":   imports,
        "lines":     js.count("\n") + 1,
    }
