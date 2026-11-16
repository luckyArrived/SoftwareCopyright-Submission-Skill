# OfficeCLI DOCX 后端

## 固定版本与边界

- 已验证版本：`1.0.151`。
- 官方发布页：https://github.com/iOfficeAI/OfficeCLI/releases/tag/v1.0.151
- 本仓库不复制 OfficeCLI 源码或二进制；OfficeCLI 继续按其 Apache-2.0 许可证独立分发。
- OfficeCLI 必须全局安装，不下载到被分析项目、本 skill 或输出目录，也不使用项目内 `工具/` 文件夹保存二进制。
- Python 保留项目分析、业务草稿、代码选择、物理行折行、选材量估算和门禁逻辑；OfficeCLI 负责 DOCX 创建、编辑、校验和预览，最终分页由 Word 排版引擎自动完成。
- 运行时设置 `OFFICECLI_SKIP_UPDATE=1` 和 `OFFICECLI_NO_AUTO_RESIDENT=1`，避免版本漂移、后台文件锁和延迟落盘。

## 全局安装与检测

Windows PowerShell 使用官方安装命令：

```powershell
irm https://raw.githubusercontent.com/iOfficeAI/OfficeCLI/main/install.ps1 | iex
```

官方脚本默认安装到 `%LOCALAPPDATA%\OfficeCLI` 并写入用户 PATH。安装完成后，必须重启 Codex，让新进程读取更新后的 PATH；重启后运行 `officecli --version` 和环境检查，再继续工作流。不得要求用户设置 `OFFICECLI_PATH`，不得通过 `--officecli` 指定项目内或任意文件夹中的可执行文件。

运行时只从当前进程 PATH 查找全局 `officecli` / `officecli.exe`。如果 Windows 官方安装目录中已有二进制、但当前进程 PATH 尚未识别，环境检查必须报告“需要重启 Codex”并停止，不得把该文件当作项目便携版直接绕过重启。

版本缺失或不等于 `1.0.151` 时，环境检查必须停止。只有用户明确接受兼容性风险后，正式生成才允许传入 `--allow-untested-officecli`。

## 写入与校验

- 使用 OfficeCLI 创建操作手册和运行界面说明 DOCX。页眉使用确认的软件全称、版本和 PAGE 字段。截图按运行证据清单逐项嵌入。
- 主要内容完成后读取 `/theme`，将主题的拉丁、东亚、复杂文字字体统一为 Times New Roman 和 SimSun，通过 OfficeCLI `raw-set` 更新并重新核对。
- 使用 `officecli validate` 验证 OpenXML 结构。脚本另重读手册检查实嵌图片张数及占位文字。打开最终文档核对每张图的清晰度及相应操作说明。
- 源程序固定分页 PDF 由 ReportLab 生成，由 pdfplumber 逐页复核。
