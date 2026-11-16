#!/usr/bin/env python3
"""Build final DOCX/TXT files from confirmed Markdown drafts with OfficeCLI."""

from __future__ import annotations

import argparse
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile
from typing import Any

from common import (
    confirmation_is_current,
    draft_completeness_issues,
    draft_snapshot,
    ensure_dir,
    file_sha256,
    read_json,
    safe_filename,
)
from extract_code_material import collect_source, submission_pages
from runtime_evidence import validate_evidence
from submission_code_pdf import write_source_pdf
from officecli_backend import OfficeCli, OfficeCliError, issue_count, json_data, structural_error_count


DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
THEME_FONT_TARGETS = {
    "major.latin": "Times New Roman",
    "major.ea": "SimSun",
    "major.cs": "Times New Roman",
    "minor.latin": "Times New Roman",
    "minor.ea": "SimSun",
    "minor.cs": "Times New Roman",
}


def parse_application_lines(md_path: Path) -> tuple[list[str], list[str]]:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    fields = [line.strip() for line in lines if line.strip().startswith("➤")]
    warnings = [line for line in fields if "待用户确认" in line]
    return fields, warnings


def parse_application_field(md_path: Path, field_name: str) -> str:
    if not md_path.exists():
        return ""
    prefix = f"➤{field_name}："
    for line in md_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return ""


def application_version(draft_dir: Path) -> str:
    version = parse_application_field(draft_dir / "申请表信息.md", "版本号")
    return "" if "待用户确认" in version else version


def application_software_name(draft_dir: Path) -> str:
    name = parse_application_field(draft_dir / "申请表信息.md", "软件全称")
    return "" if "待用户确认" in name else name


def write_application_txt(draft_dir: Path, out_dir: Path) -> tuple[Path | None, list[str]]:
    md_path = draft_dir / "申请表信息.md"
    if not md_path.exists():
        return None, ["缺少草稿/申请表信息.md"]
    fields, warnings = parse_application_lines(md_path)
    out_path = out_dir / "申请表信息.txt"
    out_path.write_text("\n".join(fields) + "\n", encoding="utf-8")
    return out_path, warnings


def read_json_if_exists(path: Path) -> dict[str, Any]:
    return read_json(path) if path.exists() else {}


def confirmation_issues(workdir: Path) -> list[str]:
    draft_dir = workdir / "草稿"
    issues: list[str] = []
    business = read_json_if_exists(draft_dir / "业务理解.json")
    if not business or not business.get("user_confirmed"):
        issues.append("业务理解尚未确认：请确认 草稿/业务理解.md 后记录 `business` 门禁")
    elif not confirmation_is_current(business):
        issues.append("业务理解在确认后已被修改：请重新记录 `business` 门禁")
    selection = read_json_if_exists(draft_dir / "代码文件选择.json")
    if not selection or not selection.get("user_confirmed"):
        issues.append("代码文件选择尚未确认：请确认 草稿/代码文件选择.json 后记录 `code-selection` 门禁")
    elif not confirmation_is_current(selection):
        issues.append("代码文件选择在确认后已被修改：请重新记录 `code-selection` 门禁")
    screenshot = read_json_if_exists(workdir / "截图方式确认.json")
    if not screenshot.get("screenshot_method_confirmed"):
        issues.append("截图方式尚未确认：请选择截图方式后记录 `screenshot-method` 门禁")
    elif screenshot.get("screenshot_method") not in {"playwright-cli", "user-supplied", "skip"}:
        issues.append("截图方式已失效：请重新选择 Playwright CLI 自动截图、用户自行截图或跳过截图")
    app_md = draft_dir / "申请表信息.md"
    if app_md.exists():
        _, warnings = parse_application_lines(app_md)
        if warnings:
            issues.append("申请表信息仍包含“待用户确认”字段")
    else:
        issues.append("缺少 草稿/申请表信息.md")
    app_confirmation = read_json_if_exists(draft_dir / "申请表字段确认.json")
    if not app_confirmation.get("application_fields_confirmed"):
        issues.append("申请表字段尚未确认：请补全字段后记录 `application-fields` 门禁")
    elif not app_md.exists() or app_confirmation.get("application_md_sha256") != file_sha256(app_md):
        issues.append("申请表信息在确认后已被修改：请重新记录 `application-fields` 门禁")
    markdown_confirmation = read_json_if_exists(draft_dir / "最终生成确认.json")
    if not markdown_confirmation.get("markdown_confirmed"):
        issues.append("Markdown 草稿尚未最终确认：请确认全部草稿后记录 `markdown` 门禁")
    elif markdown_confirmation.get("draft_file_sha256") != draft_snapshot(workdir):
        issues.append("Markdown/JSON 草稿在最终确认后已有变化：请重新记录 `markdown` 门禁")
    issues.extend(draft_completeness_issues(workdir))
    return issues


def header_commands(software_name: str, version: str) -> list[dict[str, Any]]:
    """Create a left title and right page-number region in the default header."""
    header_path = "/header[1]/p[1]"
    return [
        {"command": "add", "parent": "/", "type": "header", "props": {
            "type": "default", "text": f"{software_name} {version}", "align": "left",
            "font": "SimSun", "size": "9pt", "color": "#000000"}},
        {"command": "add", "parent": header_path, "type": "ptab",
         "props": {"align": "right", "relativeTo": "margin", "leader": "none"}},
        {"command": "add", "parent": header_path, "type": "run",
         "props": {"text": "第 ", "font": "SimSun", "size": "9pt", "color": "#000000"}},
        {"command": "add", "parent": header_path, "type": "field",
         "props": {"fieldType": "page", "font": "SimSun", "size": "9pt", "color": "#000000"}},
        {"command": "add", "parent": header_path, "type": "run",
         "props": {"text": " 页", "font": "SimSun", "size": "9pt", "color": "#000000"}},
    ]


def document_commands(software_name: str, version: str) -> list[dict[str, Any]]:
    margin = "2.5cm"
    commands: list[dict[str, Any]] = [
        {"command": "set", "path": "/", "props": {
            "docDefaults.font": "SimSun", "docDefaults.font.eastAsia": "SimSun",
            "docDefaults.font.hAnsi": "Times New Roman", "docDefaults.fontSize": "10.5pt",
            "docDefaults.color": "#000000", "updateFields": "true",
            "title": f"{software_name} {version}"}},
        {"command": "set", "path": "/section[1]", "props": {
            "pageWidth": "21cm", "pageHeight": "29.7cm", "orientation": "portrait",
            "marginTop": margin, "marginBottom": margin, "marginLeft": margin, "marginRight": margin,
            "marginHeader": "0.9cm", "marginFooter": "0.9cm", "pageStart": "1"}},
    ]
    commands.extend(header_commands(software_name, version))
    return commands


def theme_xml_from_payload(payload: dict[str, Any]) -> str:
    value = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise OfficeCliError("OfficeCLI 未返回可读取的 DOCX 主题 XML")
    return value


def theme_font_slots(theme_xml: str) -> dict[str, str]:
    try:
        root = ET.fromstring(theme_xml)
    except ET.ParseError as exc:
        raise OfficeCliError(f"DOCX 主题 XML 无法解析：{exc}") from exc
    ns = {"a": DRAWINGML_NS}
    slots: dict[str, str] = {}
    for family in ("major", "minor"):
        parent = root.find(f".//a:{family}Font", ns)
        if parent is None:
            raise OfficeCliError(f"DOCX 主题缺少 {family}Font")
        for script in ("latin", "ea", "cs"):
            node = parent.find(f"a:{script}", ns)
            if node is None:
                raise OfficeCliError(f"DOCX 主题缺少 {family}Font/{script}")
            slots[f"{family}.{script}"] = node.get("typeface", "")
    return slots


def normalize_theme_fonts_xml(theme_xml: str) -> str:
    try:
        root = ET.fromstring(theme_xml)
    except ET.ParseError as exc:
        raise OfficeCliError(f"DOCX 主题 XML 无法解析：{exc}") from exc
    ns = {"a": DRAWINGML_NS}
    for family in ("major", "minor"):
        parent = root.find(f".//a:{family}Font", ns)
        if parent is None:
            raise OfficeCliError(f"DOCX 主题缺少 {family}Font")
        # Script-specific font entries can make WPS request fonts that the
        # document never uses. Keep only the three deterministic fallbacks.
        for node in list(parent):
            if node.tag == f"{{{DRAWINGML_NS}}}font":
                parent.remove(node)
    for slot, typeface in THEME_FONT_TARGETS.items():
        family, script = slot.split(".", 1)
        node = root.find(f".//a:{family}Font/a:{script}", ns)
        if node is None:
            raise OfficeCliError(f"DOCX 主题缺少 {family}Font/{script}")
        node.set("typeface", typeface)
    ET.register_namespace("a", DRAWINGML_NS)
    return ET.tostring(root, encoding="unicode")


def verify_docx_theme_fonts(cli: OfficeCli, output: Path) -> dict[str, str]:
    theme_xml = theme_xml_from_payload(cli.raw(output, "/theme"))
    slots = theme_font_slots(theme_xml)
    mismatches = {
        slot: value for slot, value in slots.items()
        if value != THEME_FONT_TARGETS[slot]
    }
    if mismatches:
        details = "，".join(f"{slot}={value or '<空>'}" for slot, value in mismatches.items())
        raise OfficeCliError(f"{output.name} 主题字体校验失败：{details}")
    root = ET.fromstring(theme_xml)
    font_scheme = root.find(f".//{{{DRAWINGML_NS}}}fontScheme")
    if font_scheme is None:
        raise OfficeCliError(f"{output.name} 主题缺少 fontScheme")
    allowed = set(THEME_FONT_TARGETS.values())
    unexpected = sorted({
        node.get("typeface", "")
        for node in font_scheme.iter()
        if node.get("typeface") and node.get("typeface") not in allowed
    })
    if unexpected:
        raise OfficeCliError(f"{output.name} 主题仍引用其他字体：{'、'.join(unexpected)}")
    return slots


def normalize_docx_theme_fonts(cli: OfficeCli, output: Path) -> None:
    current = theme_xml_from_payload(cli.raw(output, "/theme"))
    normalized = normalize_theme_fonts_xml(current)
    # OfficeCLI 1.0.151 may report success without persisting descendant
    # setattr operations on /theme. Replacing the complete root is reliable.
    cli.raw_set(output, "/theme", "/a:theme", "replace", normalized)
    verify_docx_theme_fonts(cli, output)


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
SCREENSHOT_PLACEHOLDER_RE = re.compile(r"【截图预留：([^】]*)】")
SCREENSHOT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def resolve_screenshot_path(raw_path: str, workdir: Path, manifest_path: Path) -> Path | None:
    source = Path(raw_path)
    if source.is_absolute():
        candidates = [source]
    else:
        candidates = [
            Path.cwd() / source,
            workdir / source,
            workdir.parent / source,
            manifest_path.parent / source,
            manifest_path.parent / source.name,
        ]
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() in SCREENSHOT_EXTENSIONS:
            return candidate.resolve()
    return None


def screenshot_paths_from_manifest(manifest_path: Path, workdir: Path) -> tuple[list[Path | None], list[str]]:
    data = read_json_if_exists(manifest_path)
    entries = data.get("screenshots") or []
    if not isinstance(entries, list):
        return [], ["操作手册截图清单中的 screenshots 不是列表；已保留截图预留位置"]
    paths: list[Path | None] = []
    warnings: list[str] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            warnings.append(f"截图清单第 {index} 项格式无效；该项未插入")
            paths.append(None)
            continue
        raw_path = str(entry.get("path") or "").strip()
        if not raw_path:
            warnings.append(f"截图清单第 {index} 项缺少 path；该项未插入")
            paths.append(None)
            continue
        resolved = resolve_screenshot_path(raw_path, workdir, manifest_path)
        if resolved is None:
            warnings.append(f"截图清单第 {index} 项文件不存在或格式不支持：{raw_path}")
            paths.append(None)
            continue
        paths.append(resolved)
    return paths, warnings


def prepare_manual_markdown(
    md_path: Path,
    base_dir: Path,
    output: Path,
    screenshot_paths: list[Path | None] | None = None,
) -> list[dict[str, Any]]:
    """Replace local Markdown images with stable placeholders for later embedding."""
    images: list[dict[str, Any]] = []
    text = md_path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^```text\nSTOP_FOR_USER\nNEXT_ACTION:[^\n]*\n```\s*\Z", "", text)
    text = re.sub(r"<!--[^>]*截图[^>]*-->", "【截图预留：请在此处插入当前功能页面或操作结果截图。】", text)

    def register_image(path: Path, alt: str, origin: str) -> str:
        placeholder = f"OCLI_IMAGE_{len(images) + 1:04d}"
        images.append({"placeholder": placeholder, "path": path.resolve(), "alt": alt, "origin": origin})
        return f"\n\n{placeholder}\n\n"

    def replace(match: re.Match[str]) -> str:
        alt = match.group(1).strip() or "操作截图"
        raw_target = match.group(2).strip().strip("<>")
        target = re.sub(r'\s+["\'][^"\']*["\']\s*$', "", raw_target).strip()
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target):
            return f"\n\n【远程图片未嵌入：{alt}（{target}）】\n\n"
        image_path = (base_dir / target).resolve()
        if not image_path.is_file():
            return f"\n\n【截图缺失：{target}】\n\n"
        return register_image(image_path, alt, "markdown")

    text = IMAGE_RE.sub(replace, text)
    screenshot_iter = iter(screenshot_paths or [])

    def replace_screenshot_placeholder(match: re.Match[str]) -> str:
        try:
            image_path = next(screenshot_iter)
        except StopIteration:
            return match.group(0)
        if image_path is None:
            return match.group(0)
        alt = match.group(1).strip().rstrip("。") or "操作截图"
        return register_image(image_path, alt, "screenshot-manifest")

    output.write_text(SCREENSHOT_PLACEHOLDER_RE.sub(replace_screenshot_placeholder, text), encoding="utf-8")
    return images


def body_children(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for result in json_data(payload).get("results", []):
        if isinstance(result, dict) and result.get("path") == "/body":
            children = result.get("children")
            return children if isinstance(children, list) else []
    return []


def manual_format_commands(children: list[dict[str, Any]], images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    image_by_placeholder = {item["placeholder"]: item for item in images}
    commands: list[dict[str, Any]] = []
    for child in children:
        if child.get("type") != "paragraph" or not child.get("path"):
            continue
        path = str(child["path"])
        text = str(child.get("text") or "")
        style = str(child.get("style") or child.get("format", {}).get("style") or "")
        fmt = child.get("format") if isinstance(child.get("format"), dict) else {}
        if text in image_by_placeholder:
            image = image_by_placeholder[text]
            commands.append({"command": "set", "path": path, "props": {"text": "", "align": "center"}})
            commands.append({"command": "add", "parent": path, "type": "picture", "props": {
                "src": str(image["path"]), "width": image.get("width", "15cm"), "alt": str(image["alt"])}})
            continue
        props: dict[str, str] = {
            "font": "SimSun", "font.ea": "SimSun", "color": "#000000",
            "spaceAfter": "6pt", "lineSpacing": "1.5x", "widowControl": "true"}
        if style.lower().startswith("heading"):
            props.update({"font": "SimHei", "font.ea": "SimHei", "keepNext": "true"})
        elif fmt.get("listStyle"):
            props.update({"size": "10.5pt", "align": "left"})
        elif text.startswith("【截图") or text.startswith("【远程图片"):
            props.update({"size": "10.5pt", "align": "center"})
        else:
            props.update({"size": "10.5pt", "align": "justify", "firstLineChars": "200"})
        commands.append({"command": "set", "path": path, "props": props})
    return commands


def build_manual_docx(
    cli: OfficeCli,
    md_path: Path,
    out_path: Path,
    base_dir: Path,
    software_name: str,
    version: str,
    screenshot_paths: list[Path | None] | None = None,
) -> dict[str, int]:
    prepared: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", prefix=".officecli-manual-", dir=out_path.parent,
            encoding="utf-8", delete=False
        ) as handle:
            prepared = Path(handle.name)
        requested_screenshots = screenshot_paths or []
        images = prepare_manual_markdown(md_path, base_dir, prepared, requested_screenshots)
        if images:
            from PIL import Image

            for image in images:
                with Image.open(image["path"]) as picture:
                    image["width"] = f"{min(15, 18 * picture.width / picture.height):.2f}cm"
        manifest_image_count = sum(item.get("origin") == "screenshot-manifest" for item in images)
        remaining_placeholders = len(SCREENSHOT_PLACEHOLDER_RE.findall(prepared.read_text(encoding="utf-8")))
        commands = document_commands(software_name, version)
        commands.append({"command": "add", "parent": "/", "type": "markdown", "props": {"src": str(prepared.resolve())}})
        cli.create(out_path, commands)
        children = body_children(cli.get(out_path, "/body"))
        cli.run_batch(out_path, manual_format_commands(children, images))
        normalize_docx_theme_fonts(cli, out_path)
        return {
            "manifest_images": manifest_image_count,
            "remaining_placeholders": remaining_placeholders,
            "unused_manifest_images": max(
                0,
                sum(path is not None for path in requested_screenshots) - manifest_image_count,
            ),
        }
    finally:
        if prepared:
            prepared.unlink(missing_ok=True)


def docx_checks(cli: OfficeCli, outputs: list[Path], preview_dir: Path,
                render_preview: bool = True) -> list[str]:
    notes: list[str] = []
    if render_preview:
        ensure_dir(preview_dir)
    for output in outputs:
        verify_docx_theme_fonts(cli, output)
        validation = cli.validate(output)
        errors = structural_error_count(validation)
        if errors:
            raise OfficeCliError(f"{output.name} OpenXML 结构校验失败：{errors} 个错误")
        issues = cli.issues(output)
        notes.append(
            f"- `{output.name}`：主题字体已统一为宋体/Times New Roman；"
            f"OpenXML 结构错误 0 个；内容/格式提示 {issue_count(issues)} 个。"
        )
        if render_preview:
            preview = preview_dir / f"{output.stem}.png"
            try:
                cli.screenshot(output, preview)
                if preview.exists():
                    notes.append(f"- `{output.name}`：已生成预览 `{preview.relative_to(output.parent).as_posix()}`。")
            except (OfficeCliError, OSError) as exc:
                notes.append(f"- `{output.name}`：预览未生成（{exc}）。")
        else:
            notes.append(f"- `{output.name}`：已按参数跳过预览，OpenXML 结构校验已执行。")
    return notes


def checked_source_plan(draft_dir: Path, name: str, version: str, business: dict[str, Any]):
    manifest = read_json(draft_dir / "代码提取清单.json")
    app = draft_dir / "申请表信息.md"
    selection = draft_dir / "代码文件选择.json"
    if (manifest.get("software_name"), manifest.get("version")) != (name, version):
        raise ValueError("源码清单的名称或版本与申请表不一致，请按确认后的名称与版本重新抽取")
    if file_sha256(selection) != manifest.get("selection_sha256"):
        raise ValueError("源码范围已变更或清单来自旧版，请重新抽取")
    for draft, digest in manifest["draft_sha256"].items():
        if file_sha256(draft_dir / draft) != digest:
            raise ValueError(f"源码草稿已变更，请从原始文件重新抽取：{draft}")
    rows, files = collect_source(Path(manifest["project_root"]), selection)
    if files != manifest.get("files"):
        raise ValueError("源码文件自抽取后已变更，请重新确认版本、抽取和核对")
    current_files = {file["path"] for file in files}
    for module in business.get("manual_modules", []):
        listed = module.get("source_files") or []
        if not listed or any(path not in current_files for path in listed):
            raise ValueError(f"{module.get('title') or module.get('feature')} 缺少申报范围内的功能源码依据")
    mode, pages, _ = submission_pages(rows)
    if mode != manifest.get("mode") or len(pages) != manifest.get("submitted_page_count"):
        raise ValueError("源码交存模式或页数与抽取清单不一致")
    declared = parse_application_field(app, "源程序量").replace(",", "")
    submitted = parse_application_field(app, "页数")
    if not declared.isdecimal() or int(declared) != len(rows):
        raise ValueError(f"申请表源程序量与已确认范围不一致。当前范围实际有 {len(rows)} 条非空源码。")
    if not submitted.isdecimal() or int(submitted) != len(pages):
        raise ValueError(f"申请表交存页数与实际计划不一致，应为 {len(pages)} 页。")
    return pages


def verify_manual_images(path: Path, expected: int) -> None:
    drawingml = "http://schemas.openxmlformats.org/drawingml/2006/main"
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    relationships = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with ZipFile(path) as document:
        root = ET.fromstring(document.read("word/document.xml"))
        pictures = [node for node in root.iter(f"{{{drawingml}}}blip") if node.get(f"{{{relationships}}}embed")]
        text = "".join(node.text or "" for node in root.iter(f"{{{word}}}t"))
    if len(pictures) != expected or re.search(r"OCLI_IMAGE_\d+|STOP_FOR_USER|NEXT_ACTION:|【(?:截图预留|截图缺失|远程图片)", text):
        raise ValueError("手册成稿的内嵌运行图张数不符，或仍有截图占位")


def build_all(workdir: Path, software_name: str, version: str, skip_preview: bool,
              allow_untested_officecli: bool = False, code_font: Path | None = None) -> dict[str, Any]:
    draft_dir = workdir / "草稿"
    app_name = application_software_name(draft_dir)
    app_version = application_version(draft_dir)
    safe_name = safe_filename(app_name)
    warnings = []
    if (software_name, version) != (app_name, app_version):
        warnings.append("已采用申请表确认的软件全称及版本号")
    manual = draft_dir / "操作手册.md"
    text = manual.read_text(encoding="utf-8")
    if app_name not in text or app_version not in text:
        raise ValueError("手册草稿没有体现申请表确认的名称与版本，请同步修订")
    business = read_json(draft_dir / "业务理解.json")
    images, explanation = validate_evidence(workdir, manual, app_name, app_version, business)
    pages = checked_source_plan(draft_dir, app_name, app_version, business)
    cli = OfficeCli(require_tested_version=not allow_untested_officecli)

    with tempfile.TemporaryDirectory(prefix=".submission-", dir=workdir) as directory:
        staging = Path(directory)
        source_out = staging / f"{safe_name} 源程序鉴别材料.pdf"
        manual_out = staging / f"{safe_name} 操作手册.docx"
        write_source_pdf(source_out, app_name, app_version, pages, code_font)
        build_manual_docx(cli, manual, manual_out, draft_dir, app_name, app_version, images)
        verify_manual_images(manual_out, len(images))
        document_outputs = [manual_out]
        if explanation:
            statement = staging / "运行界面说明.md"
            statement.write_text(f"# 运行界面说明\n\n{app_name} {app_version}\n\n{explanation}\n", encoding="utf-8")
            interface_out = staging / f"{safe_name} 运行界面说明.docx"
            build_manual_docx(cli, statement, interface_out, staging, app_name, app_version)
            verify_manual_images(interface_out, 0)
            document_outputs.append(interface_out)
        application, app_warnings = write_application_txt(draft_dir, staging)
        warnings.extend(app_warnings)
        outputs = [source_out, *document_outputs, application]
        notes = docx_checks(cli, document_outputs, staging / "预览", render_preview=not skip_preview)
        notes += [
            f"- 源程序鉴别材料 PDF 复核通过，共 {len(pages)} 页，页码 1–{len(pages)}，"
            f"每页有效源码行数为 {min(map(len, pages))}–{max(map(len, pages))}。",
            f"- 操作手册实嵌入 {len(images)} 张经过运行证据清单核对的截图。提交前请打开成稿复核界面清晰度与文字说明。",
        ]
        (staging / "补正提交说明.txt").write_text(
            f"{app_name} {app_version}\n\n"
            f"文档鉴别材料上传《{manual_out.name}》。\n"
            + (f"本案要求单独说明界面形态时，附《{interface_out.name}》。\n" if explanation else "")
            + f"程序鉴别材料上传《{source_out.name}》。\n申请表信息仅供核对填写。\n",
            encoding="utf-8",
        )
        outputs.append(staging / "补正提交说明.txt")
        report = write_report(staging, outputs, warnings, notes, cli.version)
        final_dir = ensure_dir(workdir / "正式资料")
        for file in [*outputs, report]:
            file.replace(final_dir / file.name)
        for suffix in ("-代码(前30页).docx", "-代码(后30页).docx", "-代码(全部).docx", "_操作手册.docx"):
            (final_dir / f"{safe_name}{suffix}").unlink(missing_ok=True)
        if not explanation:
            (final_dir / f"{safe_name} 运行界面说明.docx").unlink(missing_ok=True)
        preview = staging / "预览"
        if preview.is_dir():
            destination = ensure_dir(final_dir / "预览")
            for file in preview.iterdir():
                if file.is_file():
                    file.replace(destination / file.name)

    return {"outputs": [str(final_dir / file.name) for file in outputs],
            "warnings": warnings, "report": str(final_dir / report.name)}


def write_report(workdir: Path, outputs: list[Path], warnings: list[str], notes: list[str], officecli_version: str) -> Path:
    report = workdir / "生成报告.md"
    lines = ["# 生成报告", "", f"- DOCX 后端：OfficeCLI {officecli_version}", "- 自动更新：已禁用", "", "## 输出文件", ""]
    for path in outputs:
        size = path.stat().st_size if path.exists() else 0
        lines.append(f"- `{path.name}` ({size} bytes)")
    lines.extend(["", "## 警告", ""])
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("- 无")
    lines.extend(["", "## 成稿校验", "", *notes, ""])
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default="软件著作权申请资料")
    parser.add_argument("--software-name", required=True)
    parser.add_argument("--version", default="V1.0")
    parser.add_argument("--allow-untested-officecli", action="store_true")
    parser.add_argument("--skip-preview", action="store_true")
    parser.add_argument("--code-font", type=Path, help="可嵌入正文的 TrueType 字体路径")
    args = parser.parse_args()
    workdir = Path(args.workdir)
    try:
        issues = confirmation_issues(workdir)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"资料核验失败：{exc}") from exc
    if issues:
        print("STOP_FOR_USER")
        print("NEXT_ACTION: 正式材料生成前必须完成以下确认：")
        for issue in issues:
            print(f"- {issue}")
        raise SystemExit(2)
    try:
        result = build_all(workdir, args.software_name, args.version, args.skip_preview,
                           args.allow_untested_officecli, args.code_font)
    except (OfficeCliError, OSError, KeyError, ValueError) as exc:
        raise SystemExit(f"SUBMISSION_BUILD_FAILED\n{exc}") from exc
    print(f"OK final materials: {workdir / '正式资料'}")
    for output in result["outputs"]:
        print(output)
    if result["warnings"]:
        print("Warnings:")
        for warning in result["warnings"]:
            print(f"- {warning}")
    print(f"Report: {result['report']}")


if __name__ == "__main__":
    main()
