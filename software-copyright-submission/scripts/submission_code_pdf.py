"""Write source identification material with fixed pages and verify the rendered PDF."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from extract_code_material import SourceLine


def default_cjk_font() -> Path | None:
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/simsun.ttc",
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        Path("/Applications/Microsoft Word.app/Contents/Resources/DFonts/Simsun.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ]
    return next((path for path in candidates if path.is_file()), None)


def write_source_pdf(
    target: Path, software_name: str, version: str, pages: Sequence[Sequence[SourceLine]], font_path: Path | None,
) -> None:
    try:
        import pdfplumber
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen.canvas import Canvas
    except ImportError as exc:
        raise ValueError("请在同一 Python 环境安装 reportlab 和 pdfplumber 后生成源码 PDF") from exc

    width, height = A4
    label = f"{software_name} {version}"
    font_path = font_path or default_cjk_font()
    font = None
    if font_path:
        try:
            font = TTFont("SubmissionCJK", str(font_path))
            pdfmetrics.registerFont(font)
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法加载可嵌入的代码字体：{font_path}") from exc
    coverage = font.face.charWidths if font else {}

    def font_for(character: str) -> str:
        if " " <= character <= "~":
            return "Courier"
        if ord(character) in coverage:
            return "SubmissionCJK"
        raise ValueError(f"缺少字符 U+{ord(character):04X} 所需的可嵌入字体，请用 --code-font 指定 TrueType 字体")

    def segments(value: str, size: float, max_width: float) -> list[str]:
        breaks = []
        start = 0
        span = 0.0
        for index, char in enumerate(value):
            w = pdfmetrics.stringWidth(char, font_for(char), size)
            if span + w > max_width and index > start:
                breaks.append(value[start:index])
                start = index
                span = 0
            span += w
        breaks.append(value[start:])
        return breaks

    def draw(pdf, value: str, x: float, y: float, size: float) -> None:
        text = pdf.beginText(x, y)
        last = None
        for char in value:
            selected = font_for(char)
            if selected != last:
                text.setFont(selected, size)
                last = selected
            text.textOut(char)
        pdf.drawText(text)

    render = Canvas(str(target), pagesize=A4, pageCompression=1)
    render.setTitle(f"{label} 源程序鉴别材料")
    for number, page in enumerate(pages, 1):
        draw(render, label, 38, height - 34, 10)
        render.setFont("Courier", 10)
        render.drawRightString(width - 38, height - 34, str(number))
        render.line(38, height - 42, width - 38, height - 42)
        for size in (8.5, 8.25, 8.0, 7.75, 7.5, 7.25):
            lines: list[tuple[int | None, list[str]]] = []
            previous = None
            for row in page:
                if row.path != previous:
                    lines.append((None, segments(row.path, size, width - 110)))
                    previous = row.path
                lines.append((row.number, segments(row.text.expandtabs(4), size, width - 110)))
            physical_rows = sum(len(parts) for _, parts in lines)
            leading = min(13.5, (height - 95) / physical_rows)
            if leading >= size + 1.05:
                break
        else:
            raise ValueError(f"第 {number} 页源码过密，当前字体下无法清晰显示。请核查源码范围、生成代码和可用字体。")
        y = height - 55
        for row_number, parts in lines:
            if row_number is not None:
                render.setFont("Courier", 7.1)
                render.drawRightString(66, y, str(row_number))
            for part in parts:
                draw(render, part, 73, y, size)
                y -= leading
        render.showPage()
    render.save()

    def compact(value: str) -> str:
        return "".join(value.split())

    with pdfplumber.open(target) as document:
        if len(document.pages) != len(pages):
            raise ValueError("源码 PDF 实际页数不符")
        for number, (page, rows) in enumerate(zip(document.pages, pages, strict=True), 1):
            header = page.crop((35, 20, width - 35, 43)).extract_text()
            if compact(header or "") != compact(label + str(number)):
                raise ValueError(f"源码 PDF 第 {number} 页的名称、版本或页码无法核验")
            extracted = []
            # Source numbers all end at x=66. File labels start at x=73, so the
            # left gutter measures original source lines independently of wraps.
            for line in page.extract_text_lines(return_chars=True):
                if line["top"] < 46:
                    continue
                glyphs = line["chars"]
                gutter = "".join(glyph["text"] for glyph in glyphs if glyph["x1"] <= 66.1)
                if gutter.isdecimal():
                    extracted.append(int(gutter))
            if extracted != [row.number for row in rows]:
                raise ValueError(f"源码 PDF 第 {number} 页的原始行号或有效行数不符")
            if any(char["x1"] > width - 33 or char["bottom"] > height - 30 for char in page.chars):
                raise ValueError(f"源码 PDF 第 {number} 页存在超出页面边距的字符")
            page.close()
