from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_docx_from_md import checked_source_plan
from common import confirmation_payload_sha256, draft_snapshot, write_json
from extract_code_material import SourceLine, extract, submission_pages
from generate_application_info import total_source_line_count
from runtime_evidence import validate_evidence


class SubmissionValidationTests(unittest.TestCase):
    def test_threshold_counts_source_lines_and_keeps_front_and_back_contiguous(self):
        for total in (300, 2999, 3000, 3001, 3079, 4107):
            with self.subTest(total=total):
                rows = [SourceLine("src.py", i, "x" * (i % 150 + 1)) for i in range(1, total + 1)]
                mode, pages, _ = submission_pages(rows)
                front = [row.number for page in pages[:30] for row in page]
                back = [row.number for page in pages[-30:] for row in page]
                if total > 3000:
                    self.assertEqual(mode, "front30_back30")
                    self.assertEqual(len(pages), 60)
                    self.assertTrue(all(len(page) >= 50 for page in pages))
                    self.assertEqual(front, list(range(1, len(front) + 1)))
                    self.assertEqual(back, list(range(total - len(back) + 1, total + 1)))
                    self.assertLess(front[-1], back[0])
                else:
                    self.assertEqual([row for page in pages for row in page], rows)

    def test_app_uses_scoped_count_and_refuses_a_stale_source(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            project = workdir / "project"
            project.mkdir()
            source = project / "main.py"
            source.write_text("print('test')\n\n", encoding="utf-8")
            (project / "other.py").write_text("other()\n" * 3000, encoding="utf-8")
            draft = workdir / "草稿"
            draft.mkdir()
            pick = draft / "代码文件选择.json"
            selection = {
                "user_confirmed": True, "project_root": str(project),
                "scope_description": "命令行工具单模块",
                "files": [{"path": source.name, "selected": True}],
            }
            selection["confirmed_content_sha256"] = confirmation_payload_sha256(selection)
            write_json(pick, selection)
            manifest = extract(project, draft, "测试软件", "V1.0", 50, pick)
            self.assertEqual(total_source_line_count({"source": {"line_count": 3002}}, manifest), 1)
            (draft / "申请表信息.md").write_text("➤源程序量：1\n➤页数：1\n", encoding="utf-8")
            business = {"manual_modules": [{"title": "运行", "source_files": ["main.py"]}]}
            self.assertEqual(len(checked_source_plan(draft, "测试软件", "V1.0", business)), 1)
            source.write_text("print('changed')\n\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "源码文件自抽取后已变更"):
                checked_source_plan(draft, "测试软件", "V1.0", business)

    def test_missing_completed_state_blocks_a_graphical_manual(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            draft = workdir / "草稿"
            draft.mkdir()
            manual = draft / "操作手册.md"
            manual.write_text("【截图预留：准备】\n\n【截图预留：完成】\n", encoding="utf-8")
            business = {
                "interface_type": "graphical",
                "manual_modules": [{"title": "处理", "required_evidence_states": ["准备", "完成"]}],
            }
            evidence = {"software_name": "示例软件", "version": "V1.0", "interface": "graphical",
                        "features": [{"module": "处理", "states": [{"state": "准备", "slot": "准备"}]}]}
            write_json(draft / "运行证据.json", evidence)
            with self.assertRaisesRegex(ValueError, "完成"):
                validate_evidence(workdir, manual, "示例软件", "V1.0", business)

    def test_command_line_name_and_statement_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            draft = workdir / "草稿"
            draft.mkdir()
            manual = draft / "操作手册.md"
            manual.write_text("运行命令后返回结果。", encoding="utf-8")
            business = {"interface_type": "command_line",
                        "manual_modules": [{"title": "查询", "required_evidence_states": ["输出"]}]}
            evidence = {
                "software_name": "查询命令行软件", "version": "V1.0",
                "interface": "command_line", "type_in_name": "命令行",
                "interface_statement": "从系统终端运行，结果写入标准输出。",
                "features": [{"module": "查询", "states": [{"state": "输出", "observed": "找到记录",
                                                           "origin": "本地真实命令"}]}],
            }
            manifest = draft / "运行证据.json"
            write_json(manifest, evidence)
            before = draft_snapshot(workdir)
            self.assertEqual(validate_evidence(workdir, manual, "查询命令行软件", "V1.0", business), ([], evidence["interface_statement"]))
            evidence["type_in_name"] = "桌面"
            write_json(manifest, evidence)
            self.assertNotEqual(before, draft_snapshot(workdir))
            with self.assertRaisesRegex(ValueError, "正式全称"):
                validate_evidence(workdir, manual, "查询命令行软件", "V1.0", business)
