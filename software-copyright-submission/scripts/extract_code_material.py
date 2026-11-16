#!/usr/bin/env python3
"""Extract real source code and create Markdown draft pages."""

from __future__ import annotations

import argparse
import re
from typing import NamedTuple
import unicodedata
from pathlib import Path
from typing import Any

from common import (
    CODE_LINES_PER_PAGE,
    CODE_MAX_COLUMNS,
    FRONTEND_EXTS,
    confirmation_is_current,
    ensure_dir,
    file_sha256,
    is_source_candidate,
    read_json,
    read_text,
    rel,
    safe_filename,
    write_json,
)


LINES_PER_PAGE = CODE_LINES_PER_PAGE
SPLIT_THRESHOLD_PAGES = 60
MAX_CODE_COLUMNS = CODE_MAX_COLUMNS


def category_weight(path: Path, project: Path) -> tuple[int, str]:
    r = rel(path, project).lower()
    name = path.name.lower()
    priority = 80
    if name in {"main.ts", "main.js", "main.tsx", "main.jsx", "app.vue", "app.tsx"} or r in {
        "src/app/page.tsx",
        "src/app/layout.tsx",
        "app/page.tsx",
        "app/layout.tsx",
    } or r.endswith("/src/app/page.tsx") or r.endswith("/src/app/layout.tsx"):
        priority = 0
    elif path.suffix.lower() in {".css", ".scss", ".sass", ".less"}:
        priority = 90
    elif "/router/" in r or "/routes/" in r or "router." in r or "routes." in r:
        priority = 10
    elif "/pages/" in r or "/views/" in r or "/app/" in r or "/screens/" in r:
        priority = 20
    elif "/api/" in r or "/apis/" in r or "/services/" in r or "request." in r:
        priority = 30
    elif "/store/" in r or "/stores/" in r or "/pinia/" in r or "/redux/" in r:
        priority = 40
    elif "/components/" in r:
        priority = 50
    elif "/utils/" in r or "/lib/" in r or "/hooks/" in r or "/composables/" in r:
        priority = 60
    elif path.suffix.lower() not in FRONTEND_EXTS:
        if any(part in r for part in ("/backend/app/", "/server/", "/api/", "/services/", "/models/", "/schemas/", "/workers/")):
            priority = 70
        elif name in {"docker-compose.yml", "docker-compose.yaml", "pyproject.toml"} or path.suffix.lower() in {".toml", ".yml", ".yaml"}:
            priority = 95
        else:
            priority = 100
    return priority, r


def should_skip_file(path: Path) -> bool:
    return not is_source_candidate(path)


class SourceLine(NamedTuple):
    path: str
    number: int
    text: str


def display_width(text: str) -> int:
    """Return deterministic monospace display columns for Latin and CJK text."""
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def wrap_display_line(line: str, max_columns: int = MAX_CODE_COLUMNS) -> list[str]:
    """Wrap one source line without dropping characters or relying on Word wrapping."""
    if max_columns < 8:
        raise ValueError("max_columns must be at least 8")
    expanded = line.expandtabs(4)
    if not expanded:
        return [""]
    segments: list[str] = []
    current: list[str] = []
    current_width = 0
    for char in expanded:
        char_width = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if current and current_width + char_width > max_columns:
            segments.append("".join(current))
            current = []
            current_width = 0
        current.append(char)
        current_width += char_width
    if current:
        segments.append("".join(current))
    return segments


def source_code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def material_code_lines(text: str, max_columns: int = MAX_CODE_COLUMNS) -> list[str]:
    lines: list[str] = []
    for source_line in source_code_lines(text):
        lines.extend(wrap_display_line(source_line, max_columns))
    return lines


def collect_source(project: Path, selection_path: Path | None) -> tuple[list[SourceLine], list[dict[str, Any]]]:
    if selection_path is None:
        raise ValueError("请先确认代码文件选择清单")
    selection = read_json(selection_path)
    if not selection.get("user_confirmed") or not confirmation_is_current(selection):
        raise ValueError("代码文件选择未确认或已经修改，请重新记录 code-selection")
    project = project.resolve()
    if Path(selection.get("project_root") or "").resolve() != project:
        raise ValueError("代码文件选择清单与当前项目目录不一致")

    rows: list[SourceLine] = []
    files: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for item in selection["files"]:
        if not item.get("selected"):
            continue
        path = (project / item["path"]).resolve()
        if not path.is_relative_to(project) or path in seen:
            raise ValueError(f"源码路径越界或重复：{item['path']}")
        seen.add(path)
        if not path.is_file() or should_skip_file(path):
            raise ValueError(f"已确认的源码不可读取或需要重新核对：{item['path']}")
        name = rel(path, project)
        digest = file_sha256(path)
        lines = read_text(path).removeprefix("\ufeff").splitlines()
        if file_sha256(path) != digest:
            raise ValueError(f"抽取期间源码已变更，请重新抽取：{name}")
        selected = [SourceLine(name, number, line) for number, line in enumerate(lines, 1) if line.strip()]
        if not selected:
            continue
        rows.extend(selected)
        files.append({
            "path": name,
            "source_line_count": len(lines),
            "selected_line_count": len(selected),
            "sha256": digest,
        })
    if not rows:
        raise ValueError("申报范围内没有可交存的源码")
    return rows, files


def submission_pages(rows: list[SourceLine], minimum: int = LINES_PER_PAGE) -> tuple[str, list[list[SourceLine]], int]:
    if minimum != 50:
        raise ValueError("本流程按每页 50 条有效源码作为基准")
    # Precisely 3000 lines fit as full source in 60 pages. For longer
    # programs, start with a complete pagination whose last page also has 50 lines.
    if len(rows) < 100:
        pages = paginate(rows, minimum)
        return "all_under_60_pages", pages, len(pages)
    page_count, extra = divmod(len(rows), minimum)
    pages = []
    cursor = 0
    for index in range(page_count):
        end = cursor + minimum + (index < extra)
        pages.append(rows[cursor:end])
        cursor = end
    if len(rows) <= 3000:
        return "all_under_60_pages", pages, page_count
    return "front30_back30", pages[:30] + pages[-30:], page_count


def page_draft(rows: list[SourceLine]) -> list[str]:
    last_path = None
    lines = []
    for row in rows:
        if row.path != last_path:
            lines.append(f"// File: {row.path}")
            last_path = row.path
        lines.extend(wrap_display_line(row.text))
    return lines


def paginate(lines: list[Any], lines_per_page: int) -> list[list[Any]]:
    return [lines[i : i + lines_per_page] for i in range(0, len(lines), lines_per_page)]


def write_pages_md(path: Path, title: str, software_name: str, version: str, pages: list[tuple[int, list[str]]]) -> None:
    chunks = [f"# {title}", "", f"软件名称：{software_name}", f"版本号：{version}", ""]
    for page_no, page_lines in pages:
        runs = (len(run) for line in page_lines for run in re.findall(r"`+", line))
        fence = "`" * max(3, max(runs, default=0) + 1)
        chunks.extend([f"## 第 {page_no} 页", "", fence + "text"])
        chunks.extend(page_lines)
        chunks.extend([fence, ""])
    path.write_text("\n".join(chunks), encoding="utf-8")


def write_manifest_md(path: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# 代码提取清单", "",
        f"- 软件：{manifest['software_name']} {manifest['version']}",
        f"- 项目目录：{manifest['project_root']}",
        f"- 申报范围：{manifest['scope_description']}",
        f"- 申报源程序量：{manifest['declared_source_line_count']} 条非空原始行",
        f"- 提交：{manifest['submitted_page_count']} 页，模式 {manifest['mode']}",
        "", "| 文件 | 原始物理行 | 非空行 | SHA-256 |", "| --- | ---: | ---: | --- |",
    ]
    for item in manifest["files"]:
        lines.append(f"| `{item['path']}` | {item['source_line_count']} | {item['selected_line_count']} | `{item['sha256']}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract(project: Path, out_dir: Path, software_name: str, version: str, lines_per_page: int, selection_path: Path | None) -> dict[str, Any]:
    rows, files = collect_source(project, selection_path)
    assert selection_path is not None
    selection = read_json(selection_path)
    scope = str(selection.get("scope_description") or "").strip()
    if not scope:
        raise ValueError("代码文件选择清单缺少 scope_description，请确认完整申报范围")
    mode, pages, total_pages = submission_pages(rows, lines_per_page)
    ensure_dir(out_dir)
    for name in ("代码-前30页.md", "代码-后30页.md", "代码-全部.md"):
        (out_dir / name).unlink(missing_ok=True)
    drafted = [(index, page_draft(page)) for index, page in enumerate(pages, 1)]
    outputs = {"代码-全部.md": drafted}
    if mode == "front30_back30":
        outputs = {"代码-前30页.md": drafted[:30], "代码-后30页.md": drafted[30:]}
    for name, content in outputs.items():
        write_pages_md(out_dir / name, "代码材料", software_name, version, content)
    manifest = {
        "software_name": software_name,
        "version": version,
        "project_root": str(project.resolve()),
        "scope_description": scope,
        "file_count": len(files),
        "source_line_count": sum(item["source_line_count"] for item in files),
        "selected_source_line_count": len(rows),
        "declared_source_line_count": len(rows),
        "material_line_count": sum(len(lines) for _, lines in drafted),
        "lines_per_page": lines_per_page,
        "total_pages": total_pages,
        "submitted_page_count": len(pages),
        "target_pages": SPLIT_THRESHOLD_PAGES,
        "mode": mode,
        "selection_sha256": file_sha256(selection_path),
        "draft_sha256": {name: file_sha256(out_dir / name) for name in outputs},
        "outputs": list(outputs),
        "files": files,
        "safe_software_filename": safe_filename(software_name),
    }
    write_json(out_dir / "代码提取清单.json", manifest)
    write_manifest_md(out_dir / "代码提取清单.md", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--analysis", help="Optional project analysis JSON; retained for workflow traceability")
    parser.add_argument("--software-name", required=True)
    parser.add_argument("--version", default="V1.0")
    parser.add_argument("--out-dir", default="软件著作权申请资料/草稿")
    parser.add_argument("--lines-per-page", type=int, default=LINES_PER_PAGE)
    parser.add_argument("--selection", help="Editable JSON file created by propose_code_selection.py")
    args = parser.parse_args()

    project = Path(args.project)
    if not project.exists():
        raise SystemExit(f"Project not found: {project}")
    if args.analysis and not Path(args.analysis).exists():
        raise SystemExit(f"Analysis JSON not found: {args.analysis}")

    selection = Path(args.selection) if args.selection else None
    if selection and not selection.exists():
        raise SystemExit(f"Selection JSON not found: {selection}")

    try:
        manifest = extract(project, Path(args.out_dir), args.software_name, args.version, args.lines_per_page, selection)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"OK code drafts: {args.out_dir}")
    print(f"Selected files: {manifest['file_count']}")
    print(f"Mode: {manifest['mode']}")
    print(f"Total pages: {manifest['total_pages']}")
    print(f"Outputs: {', '.join(manifest['outputs'])}")


if __name__ == "__main__":
    main()
