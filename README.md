# FR Tender To CN DOCX

## Agent Skill / 智能体技能

这是一个面向 Codex/AI agent 工作流的 agent skill。`SKILL.md` 描述了 agent 应如何识别 OCR 标书输入、调用脚本、检查 QA 摘要，并在生成 Word 文档前完成术语和结构复核。

This repository is an agent skill for Codex/AI-agent workflows. `SKILL.md` explains how an agent should identify OCR tender inputs, run the scripts, inspect QA summaries, and review terminology and structure before producing Word output.

## 中文简介

`fr-tender-to-cn-docx` 用于将法语（阿尔及利亚语境）标书或磋商文件的 OCR 结果翻译为中文，并整理输出为格式规范的 Word 文档。它适合输入为 `.md` 或 `.json` 的 OCR 文本，尤其适用于招标文件、询价文件、评分标准、技术附件和附件模板等结构复杂的采购资料。

该 Skill 的核心原则是：先用脚本批量翻译 OCR 中间稿并生成 QA 摘要，再进行术语修正和 Word 排版，而不是把长篇 OCR 原文直接交给模型逐段翻译。

## English Overview

`fr-tender-to-cn-docx` translates OCR output from French tender or consultation documents in the Algerian context into Chinese and prepares the result as a structured Word document. It is designed for OCR source files in `.md` or `.json`, especially bidding documents, RFQs, evaluation criteria, technical attachments, and annex templates.

The core workflow is script-first: batch translate the OCR intermediate text, inspect QA metrics, apply terminology cleanup, and then generate Word output. It avoids direct long-form model translation of noisy OCR source text.

## 适用场景 / Use Cases

- OCR Markdown 或 JSON 标书翻译为中文 Word。
- 法语招标文件、磋商文件、询价文件中文化。
- 保留标题、编号、表格、附件编号和空白填写区。
- 对 Sonatrach、阿尔及利亚油气采购常用术语做一致性处理。

- Translate OCR Markdown or JSON tender sources into Chinese Word documents.
- Localize French bidding, consultation, and RFQ documents into Chinese.
- Preserve headings, numbering, tables, annex numbering, and blank fields.
- Normalize Sonatrach and Algerian oil and gas procurement terminology.

## Contents

- `SKILL.md` - Codex skill instructions and translation rules.
- `references/termbase.md` - Tender terminology reference.
- `references/annex_templates.md` - Annex template reference.
- `scripts/translate_ocr_tender.py` - OCR Markdown/JSON to Chinese Markdown translator.
- `scripts/postprocess_zh_markdown.py` - Chinese Markdown terminology and punctuation cleanup.

## 安装 / Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 使用方法 / Usage

Translate OCR Markdown into Chinese Markdown:

```powershell
python .\scripts\translate_ocr_tender.py "C:\path\to\source.md" --output "C:\path\to\source.zh.md"
```

Post-process terminology:

```powershell
python .\scripts\postprocess_zh_markdown.py "C:\path\to\source.zh.md" --output "C:\path\to\source.zh.fixed.md"
```

Generate a final Word document using your preferred DOCX workflow after the Chinese Markdown has passed QA.

## QA 要求 / QA Requirements

检查翻译摘要中的 `translated`、`fallbacks`、`latin_only` 和 `garble_like`。如果主要标题仍是法文、`translated=0` 或拉丁字符残留异常多，应先处理翻译服务或 OCR 清洗问题。

Inspect `translated`, `fallbacks`, `latin_only`, and `garble_like` in the translation summary. If main headings remain French, `translated=0`, or Latin text remains unusually high, fix the translation service or OCR cleanup before delivery.

## Notes

For original `.docx` tender files, use `tender-translation-kld` instead. This skill is intended for OCR-derived `.md` and `.json` sources.
