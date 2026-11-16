# Software Copyright Submission Skill

用于中文软件著作权申请的 Codex 技能，覆盖新申请材料生成、已有资料核查和补正交付。

- 新申请从真实项目提取源码并整理操作手册、代码鉴别材料和申请表信息。
- 只读核查对照申报版本和软件形态，检查缺失的源码、运行截图和申请表依据。
- 补正按通知逐项处理，核对成片或其他完成状态截图、源码页码与行数，以及每个文件对应的上传栏目。

## 安装与使用

克隆仓库或下载 ZIP，将完整的 `software-copyright-submission/` 目录放入 Codex 可识别的技能目录。该目录包含 [SKILL.md](software-copyright-submission/SKILL.md)、脚本、参考规则和测试。

在 Codex 中调用 `$software-copyright-submission`，例如：

> 用 $software-copyright-submission 核查这套软著补正材料，先列出缺失的源码、截图和待核对字段。

只读核查根据现有材料开展。生成 Word 需 Python 3.10+ 和技能中指定的 OfficeCLI 版本。需要自动截图时，按技能中的截图工具说明准备环境。

## 上游与许可证

本仓库由 luckyArrived 于 2026-11-16 基于 Fokkyp 的 [SoftwareCopyright-Skill](https://github.com/Fokkyp/SoftwareCopyright-Skill) 本地 2.5 版本整理发布。保留上游生成流程，增加申报范围核对、运行证据与缺项核查、成稿逐页验收规则，并调整技能名称及相应配置。

本仓库沿用上游 [GNU Affero General Public License v3.0](LICENSE)。
