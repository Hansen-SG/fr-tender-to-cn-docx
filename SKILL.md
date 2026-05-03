---
name: fr-tender-to-cn-docx
description: >
  将法语（阿尔及利亚语境）标书/磋商文件翻译为中文，并输出格式规范的 Word (.docx) 文档。
  适用场景：用户上传法语标书的 OCR 结果（`.md`、`.json`），要求翻译成中文并整理排版；
  涉及招标文件、磋商文件、询价文件等采购文档，包含表格、编号列表、附件模板等复杂结构。
  触发关键词：法语标书翻译、法转中标书、招标文件中文化、appel d'offres 翻译、dossier de consultation 翻译、OCR 标书转中文 Word。
  优先使用内置脚本调用外部翻译服务完成批量翻译与 QA，不要把整篇 OCR 文本直接交给模型逐段硬翻。
---

# 法语标书 → 中文 Word 文档翻译 Skill

提供 OCR 标书的低自由度翻译流程。先用脚本批量翻译并输出 QA 摘要，再做术语修正和 Word 排版。

## Required Workflow

1. 确认输入类型。若用户给的是 `.docx` 原稿，改用 `tender-translation-kld`；若给的是 OCR 结果 `.md` / `.json`，继续使用本 skill。
2. 检查环境：确认 `Python 3.10+`、`deep-translator` 可用，并且当前环境允许访问翻译服务。若翻译 API 不可用，不要退回到整篇 AI 直译。
3. 读取 `references/termbase.md` 与 `references/annex_templates.md`，了解术语和附件模板。
4. 先运行 `scripts/translate_ocr_tender.py`，把原始 OCR `.md/.json` 翻成中文 Markdown 中间稿。该脚本会：
   - 过滤 OCR 噪音；
   - 预先删除 Markdown/HTML 中的图片块，例如 `<div ...><img ... /></div>`、独立 `<img ...>`、以及整行 `![alt](url)` 图片语法；
   - 保留 Markdown 标题、列表、表格结构；
   - 调用 Google 翻译批量翻译；
   - 保护 URL、邮箱、单位、点号缩写、机构简称；
   - 输出 `summary`、`fallbacks`、`latin_only`、`garble_like` 等 QA 指标。
5. 检查翻译摘要。若 `translated=0`，或 `latin_only` 残留异常多，或主要标题仍是法文，判定翻译失败，先解决 API/脚本问题，不得直接交付。
6. 运行 `scripts/postprocess_zh_markdown.py`，修正常见标书术语误译和 OCR 标点问题。
7. 再把中文 Markdown 映射成 Word 结构，生成 `.docx`。需要时可结合 `doc` skill 或 `python-docx` / `docx` npm 包，但排版步骤必须基于已经翻好的中文中间稿，而不是重新让模型翻译原文。
8. 交付前抽样检查：标题、表格、附件编号、金额/分值、页眉页脚、附件模板空白区、术语一致性。

## Scripts

- `scripts/translate_ocr_tender.py`
  输入 OCR `.md/.json`，输出中文 Markdown。适合长文档和高噪声 OCR 文本。
- `scripts/postprocess_zh_markdown.py`
  输入中文 Markdown，修正常见固定误译。它是译后修正，不替代主翻译。

## Translation Rules

- 优先采用 `references/termbase.md` 中的译法。
- 公司名首次出现使用“原文（中文注释）”，如 `Sonatrach（阿尔及利亚国家石油公司）`。
- 标准编号、型号、序列号、已定义缩写保留原文。
- 数值、货币、税率、分值、实施期限不得擅自改写。
- 不得整篇依赖模型直接翻译 OCR 原文；模型只用于结构判断、QA 和少量人工润色。

## OCR-Specific Rules

- 过滤带 `<img>` 的 OCR 印章/图片行和 `Page X sur Y` 页脚噪音。
- 对 Markdown 中仅用于展示 OCR 戳记/扫描碎片的图片 HTML 片段，直接删除，不参与翻译也不保留到输出。
- 对 OCR 重复复制的多列内容，先保留第一份有效文本，再决定是否在 Word 中还原为表格。
- Markdown 表格的列结构要保持；不要把表格直接压平成普通段落。
- 附件模板中的空白填写区保留为 `___________________` 或空行，不要擅自填充。

## Word Output Rules

- 章节结构优先映射为：
  - 第一部分：投标人须知
  - 第二部分：特别数据
  - 第三部分：评分标准
  - 第四部分：技术文件
  - 第五部分：附件
- 正文中文风格保持正式、客观、技术化，符合阿尔及利亚国企/油气采购文件语气。
- 若用 `docx` npm 包或 `python-docx` 生成 Word，必须保留编号、表格结构和附件编号连续性。

## Failure Modes To Guard Against

- 没有调用外部翻译服务，直接让模型翻整篇 OCR 文本，导致长文档中途失败或漏译。
- 翻译脚本失败后静默输出原文，误判为成功。
- OCR 噪音未过滤，导致页脚、印章、图片说明被翻进正文。
- 固定术语被直译，如 `Cahier des charges` 被翻成“规格”而不是“招标文件”。

## QA Checklist

- 标题是否已翻译且层级清晰。
- 表格列数、顺序、金额、分值是否保持。
- 附件编号是否连续。
- 术语是否与 `references/termbase.md` 一致。
- 是否存在明显英文/法文残留、乱码或 OCR 标点异常。
- 若未发现问题，明确写“未发现问题”。
