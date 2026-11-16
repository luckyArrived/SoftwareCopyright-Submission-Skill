"""Validate the evidence attached to each documented operation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from common import read_json

SLOT_RE = re.compile(r"【截图预留：([^】]+)】")
KINDS = {"graphical", "command_line", "headless"}


def evidence_image_paths(workdir: Path, evidence: dict[str, Any]) -> list[Path]:
    paths = []
    for feature in evidence.get("features", []):
        for state in feature.get("states", []):
            if state.get("image"):
                path = (workdir / state["image"]).resolve()
                if not path.is_relative_to(workdir.resolve()):
                    raise ValueError(f"运行图应位于资料目录内：{state['image']}")
                paths.append(path)
    return paths


def validate_evidence(
    workdir: Path, manual: Path, name: str, version: str, business: dict[str, Any],
) -> tuple[list[Path], str]:
    path = workdir / "草稿/运行证据.json"
    if not path.is_file():
        raise ValueError("正式输出须先按操作步骤核验并填写 草稿/运行证据.json")
    evidence = read_json(path)
    if evidence.get("software_name") != name or evidence.get("version") != version:
        raise ValueError("运行证据的软件名称或版本与申请表不一致")

    kind = evidence.get("interface")
    if kind not in KINDS or business.get("interface_type") != kind:
        raise ValueError("运行证据必须明确申报端的界面类型")
    explanation = ""
    if kind != "graphical":
        type_label = str(evidence.get("type_in_name") or "").strip()
        explanation = str(evidence.get("interface_statement") or "").strip()
        if (not type_label or type_label not in name or not explanation
                or (kind == "command_line" and not re.search(r"命令行|终端|控制台|CLI", type_label, re.I))):
            raise ValueError("命令行或无运行界面材料需要反映软件类型的正式全称，以及真实运行方式说明")

    manual_text = manual.read_text(encoding="utf-8")
    slots = [slot.strip() for slot in SLOT_RE.findall(manual_text)]
    if len(slots) != len(set(slots)):
        raise ValueError("手册截图预留标题重复，需分别命名")
    if re.search(r"!\[|【(?:截图缺失|远程图片)", manual_text):
        raise ValueError("正式手册的运行图须由运行证据清单匹配。请将手册内直接图片替换为命名截图预留。")
    features = evidence.get("features", [])
    modules = [str(module.get("title") or module.get("feature") or "").strip() for module in business.get("manual_modules", [])]
    required = {name: module.get("required_evidence_states") for name, module in zip(modules, business.get("manual_modules", []))}
    actual = [str(feature.get("module") or "").strip() for feature in features]
    if not modules or any(not module for module in modules) or len(set(modules)) != len(modules) or sorted(modules) != sorted(actual):
        raise ValueError("运行证据须逐项对应已确认业务理解中的手册模块名称")
    photos = {}
    for feature in features:
        states = feature.get("states", [])
        required_states = required[feature["module"]]
        if (not isinstance(required_states, list) or not required_states
                or not all(isinstance(state, str) and state for state in required_states)
                or len(set(required_states)) != len(required_states)):
            raise ValueError(f"{feature['module']} 缺少已确认的 required_evidence_states")
        observed_states = [str(state.get("state") or "") for state in states]
        if sorted(required_states) != sorted(observed_states):
            missing = [state for state in required_states if state not in observed_states]
            raise ValueError(f"{feature['module']} 的证据与已确认的状态不一致，缺项：{'、'.join(missing) or '请检查重复或多余状态'}")
        for state in states:
            state_name = str(state.get("state") or "").strip()
            description = str(state.get("observed") or "").strip()
            origin = str(state.get("origin") or "").strip()
            if not (state_name and description and origin):
                raise ValueError(f"{feature['module']} 有未经核验的运行状态或缺少证据来源")
            raw = state.get("image")
            if not raw:
                if kind == "graphical" or state.get("slot"):
                    raise ValueError(f"{feature['module']} / {state_name} 缺少真实运行图")
                continue
            slot = str(state.get("slot") or "").strip()
            image = evidence_image_paths(workdir, {"features": [{"states": [state]}]})[0]
            if not slot or slot not in slots or slot in photos:
                raise ValueError(f"{feature['module']} / {state_name} 的截图未唯一匹配手册位置")
            if not image.is_file():
                raise ValueError(f"运行图不存在：{raw}")
            try:
                from PIL import Image
            except ImportError as exc:
                raise ValueError("请安装 Pillow 以检查运行图") from exc
            try:
                with Image.open(image) as picture:
                    if picture.format not in {"PNG", "JPEG"}:
                        raise ValueError("请使用 PNG 或 JPEG")
                    picture.verify()
            except (OSError, ValueError) as exc:
                raise ValueError(f"运行图不可用：{raw}（{exc}）") from exc
            photos[slot] = image
    if set(slots) != photos.keys():
        raise ValueError("仍有截图缺失：" + "、".join(slot for slot in slots if slot not in photos))
    if kind == "graphical" and not photos:
        raise ValueError("图形界面软件没有可嵌入的运行截图")
    return [photos[slot] for slot in slots], explanation
