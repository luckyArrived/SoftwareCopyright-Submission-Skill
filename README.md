# Software Copyright Submission Skill

用于中文软件著作权申请的 Codex 技能，覆盖新申请材料生成、已有资料核查和补正交付。

- 新申请从真实项目提取源码并整理操作手册、代码鉴别材料和申请表信息。
- 只读核查对照申报版本和软件形态，检查缺失的源码、运行截图和申请表依据。
- 补正按通知逐项处理，核对成片或其他完成状态截图、源码页码与行数，以及每个文件对应的上传栏目。

## 安装与使用

克隆仓库或下载 ZIP，将完整的 `software-copyright-submission/` 目录放入 Codex 可识别的技能目录。该目录包含 [SKILL.md](software-copyright-submission/SKILL.md)、脚本、参考规则和测试。

在 Codex 中调用 `$software-copyright-submission`，例如：

> 用 $software-copyright-submission 核查这套软著补正材料，先列出缺失的源码、截图和待核对字段。

只读核查按现有材料开展。正式生成使用 Python 3.10+、OfficeCLI 1.0.151 和 `pip install -r software-copyright-submission/requirements.txt` 中的 Python 依赖。源程序包含中文或其他 Unicode 字符时，需要可嵌入且覆盖这些字符的 TrueType 字体。必要时用 `--code-font` 指定文件。

## 2.6 补正生成与适用条件

- 工作流适用于能定位申报版本及完整源码的网页、桌面、移动、命令行和服务端项目。图形界面须有对应版本的真实运行证据。有账号、设备、第三方服务或字体依赖时，需准备相应环境。
- 确认申报端和版本，使用[运行证据清单](software-copyright-submission/references/runtime_evidence.md)将功能、源码、操作步骤与截图对应。缺少应有运行图时，保留草稿供核对。命令行或无图形界面的情况以真实输出说明，并在申报名称中体现软件类型。
- 申请表程序量来自完整申报范围的非空原始源码。超过 3000 行交存前后各 30 页。每页按原始行计数，排版折行和标题不计。短项目提交全部，正好 3000 行为全部 60 页。
- 正式输出为操作手册 DOCX、固定分页源程序 PDF、申请表 TXT 和提交说明。提交前核对系统接收格式，并打开手册确认图片和操作内容。截图取证与申请表字段依赖项目事实及相应授权。

测试命令

```bash
python3 -m unittest discover -s software-copyright-submission/tests -v
```

## 上游与许可证

本仓库由 luckyArrived 于 2026-11-16 基于 Fokkyp 的 [SoftwareCopyright-Skill](https://github.com/Fokkyp/SoftwareCopyright-Skill) 本地 2.5 版本整理发布。保留上游生成流程，增加申报范围核对、运行证据与缺项核查、成稿逐页验收规则，并调整技能名称及相应配置。

本仓库沿用上游 [GNU Affero General Public License v3.0](LICENSE)。
