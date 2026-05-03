from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from deep_translator import GoogleTranslator


URL_RE = re.compile(r"https?://\S+|www\.\S+")
EMAIL_RE = re.compile(r"[\w.+'-]+@[\w-]+\.[\w.-]+")
UNIT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:%|degC|degF|km|m|mm|cm|kg|g|t|MPa|kPa|Pa|psi|bar|kW|MW|W|V|kV|A|Hz|m3|m\^3|L|ml|s|min|h|d|ppm|ppb)\b"
)
# Preserve short acronyms and mixed letter/number codes, but do not freeze
# ordinary uppercase French words such as MODE / OFFRES / PASSATION.
ABBR_RE = re.compile(r"\b(?:[A-Z]{2,5}|[A-Z0-9&/\-]*\d[A-Z0-9&/\-]*)\b")
DOTTED_ABBR_RE = re.compile(r"\b[A-Z0-9]+(?:\.[A-Z0-9]+){1,}\b")
TABLE_RULE_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
HTML_TABLE_RE = re.compile(r"<table\b.*?</table>", re.I | re.S)
IMAGE_BLOCK_PATTERNS = [
    re.compile(r"<div[^>]*>\s*<img\b.*?</div>", re.I | re.S),
    re.compile(r"<p[^>]*>\s*<img\b.*?</p>", re.I | re.S),
    re.compile(r"<img\b[^>]*?/?>", re.I | re.S),
    re.compile(r"^[ \t]*!\[[^\]]*]\([^)]+\)[ \t]*$", re.M),
]
OCR_NOISE_PATTERNS = [
    re.compile(r"<div[^>]*>\s*<img\b", re.I),
    re.compile(r"<img\b", re.I),
    re.compile(r"\bPage\s+\d+\s+sur\s+\d+\b", re.I),
    re.compile(r"\bPassations?\s+des\s+Consultation", re.I),
]
SOURCE_TERM_MAP = {
    "Processus": "流程",
    "Date": "日期",
    "Cahier des charges": "招标文件",
    "Dossier de consultation": "磋商文件",
    "Appel d'offres": "招标",
    "APPEL D'OFFRES NATIONAL ET INTERNATIONAL RESTREINT": "限制性国内及国际招标",
    "Objet du cahier des charges": "招标文件的目的",
    "Soumissionnaire": "投标人",
    "soumissionnaires retenus": "入围投标人",
    "dossiers de candidature": "候选申请文件",
    "questions d'éclaircissement": "澄清问题",
    "offres techniques préliminaires": "初步技术投标文件",
    "offres préliminaires": "初步投标文件",
    "offres techniques et financières définitives": "最终技术和商务投标文件",
    "offres techniques définitifs et financières": "最终技术和商务投标文件",
    "Clarification": "澄清",
    "candidats": "候选人",
    "Structure contractante": "采购方",
    "Offre technique": "技术标书",
    "Offre financière": "商务标书",
    "Données Particulières": "特别数据",
    "Barème d'évaluation": "评分标准",
    "Bordereau des prix unitaires": "单价表",
    "Devis quantitatif et estimatif": "工程量估价表",
    "Délai de réalisation": "实施期限",
    "Délai de garantie": "质保期限",
    "Attestation de bonne exécution": "项目完成合格证明",
    "Mise en demeure": "正式警告",
    "Workflow de validation": "验证工作流",
    "ERP": "ERP",
    "SARL 2SP": "SARL 2SP",
    "Sonatrach": "Sonatrach",
}
COMPANY_MAP = {
    "SARL 2SP": "工业设施安全与保护公司",
    "Sonatrach": "阿尔及利亚国家石油公司",
}
_SPACE_EQUIV = {" ", "\u00A0", "\u2007", "\u202F"}


@dataclass
class TranslationStats:
    total_lines: int = 0
    translatable_lines: int = 0
    translated_lines: int = 0
    skipped_noise_lines: int = 0
    fallbacks: int = 0
    latin_only_lines: list[tuple[int, str]] = field(default_factory=list)
    garble_like_lines: list[tuple[int, str]] = field(default_factory=list)


def _ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _normalize_spaces(text: str) -> str:
    return "".join(" " if ch in _SPACE_EQUIV else ch for ch in text)


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.exists():
        return path
    normalized = Path(_normalize_spaces(path_str))
    if normalized.exists():
        return normalized
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to OCR markdown or json input.")
    parser.add_argument("--output", required=True, help="Path to translated markdown output.")
    parser.add_argument("--source", default="fr", help="Source language: auto, en, fr.")
    parser.add_argument("--termbase", help="Optional termbase markdown path.")
    return parser.parse_args()


def load_termbase(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    mappings: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        source, target = cells[0], cells[1]
        if source in {"法语", "法语原文", "法语/英语", "原文"}:
            continue
        if set(source) <= {"-", ":"}:
            continue
        if source and target:
            mappings[source] = target
    return mappings


def extract_text_from_json(obj) -> list[str]:
    output: list[str] = []
    if isinstance(obj, dict):
        preferred_keys = ["title", "heading", "markdown", "content", "text", "value"]
        used = False
        for key in preferred_keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                output.extend(value.splitlines())
                used = True
        if not used:
            for value in obj.values():
                output.extend(extract_text_from_json(value))
    elif isinstance(obj, list):
        for item in obj:
            output.extend(extract_text_from_json(item))
    elif isinstance(obj, str) and obj.strip():
        output.extend(obj.splitlines())
    return output


def load_input_lines(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return extract_text_from_json(data)
    return path.read_text(encoding="utf-8").splitlines()


def load_input_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return "\n".join(extract_text_from_json(data))
    return path.read_text(encoding="utf-8")


def strip_image_blocks(raw_text: str) -> tuple[str, int]:
    removed = 0
    cleaned = raw_text

    for pattern in IMAGE_BLOCK_PATTERNS:
        def _repl(match: re.Match[str]) -> str:
            nonlocal removed
            removed += 1
            text = match.group(0)
            return "\n" * text.count("\n")

        cleaned = pattern.sub(_repl, cleaned)

    return cleaned, removed


def should_skip_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in OCR_NOISE_PATTERNS)


def should_translate_text(text: str) -> bool:
    return bool(text and text.strip() and re.search(r"[A-Za-zÀ-ÿ]", text))


def protect(text: str, source_terms: dict[str, str], prefix: str) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}
    idx = 0

    def put_placeholder(value: str) -> str:
        nonlocal idx
        key = f"⟦{idx:04d}⟧"
        placeholders[key] = value
        idx += 1
        return key

    def build_term_pattern(source: str) -> re.Pattern[str]:
        escaped = re.escape(source)
        return re.compile(rf"(?<![A-Za-zÀ-ÿ]){escaped}(?![A-Za-zÀ-ÿ])", re.I)

    for source, target in sorted(source_terms.items(), key=lambda item: len(item[0]), reverse=True):
        text = build_term_pattern(source).sub(lambda _: put_placeholder(target), text)

    for pattern in (URL_RE, EMAIL_RE, UNIT_RE, DOTTED_ABBR_RE):
        text = pattern.sub(lambda match: put_placeholder(match.group(0)), text)

    text = ABBR_RE.sub(lambda match: put_placeholder(match.group(0)), text)
    return text, placeholders


def restore(text: str, placeholders: dict[str, str]) -> str:
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def apply_company_rules(text: str, company_seen: set[str]) -> str:
    for name, zh in COMPANY_MAP.items():
        if f"{name}（{zh}）" in text:
            company_seen.add(name)
            continue
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        if pattern.search(text):
            replacement = f"{name}（{zh}）" if name not in company_seen else name
            text = pattern.sub(replacement, text)
            company_seen.add(name)
    return text


def split_markdown_prefix(line: str) -> tuple[str, str]:
    patterns = [
        r"^(\s{0,3}#{1,6}\s+)(.*)$",
        r"^(\s*[-*+]\s+)(.*)$",
        r"^(\s*\d+[.)]\s+)(.*)$",
        r"^(\s*>\s+)(.*)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, line)
        if match:
            return match.group(1), match.group(2)
    return "", line


def is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def safe_translate(translator: GoogleTranslator, text: str, stats: TranslationStats) -> tuple[str, bool]:
    try:
        result = translator.translate(text)
        time.sleep(0.02)
        return result, True
    except Exception:
        stats.fallbacks += 1
        return text, False


def safe_translate_batch(
    translator: GoogleTranslator, texts: list[str], stats: TranslationStats
) -> tuple[list[str], bool]:
    try:
        results = translator.translate_batch(texts)
        time.sleep(0.02)
        if isinstance(results, list) and len(results) == len(texts):
            return results, True
    except Exception:
        pass

    translated: list[str] = []
    batch_success = False
    for text in texts:
        result, success = safe_translate(translator, text, stats)
        translated.append(result)
        batch_success = batch_success or success
    return translated, batch_success


def translate_text(
    text: str,
    idx: int,
    translator: GoogleTranslator,
    source_terms: dict[str, str],
    stats: TranslationStats,
    cache: dict[str, str],
    company_seen: set[str],
) -> str:
    if text in cache:
        return cache[text]
    if not should_translate_text(text):
        result = apply_company_rules(text, company_seen)
        cache[text] = result
        return result

    stats.translatable_lines += 1
    protected, placeholders = protect(text, source_terms, prefix=f"L{idx}")
    translated, success = safe_translate(translator, protected, stats)
    restored = restore(translated, placeholders)
    restored = apply_company_rules(restored, company_seen)
    if success and restored != text:
        stats.translated_lines += 1
    cache[text] = restored
    return restored


def translate_text_batch(
    entries: list[tuple[int, str]],
    translator: GoogleTranslator,
    source_terms: dict[str, str],
    stats: TranslationStats,
    cache: dict[str, str],
    company_seen: set[str],
    chunk_size: int = 40,
) -> list[str]:
    results: list[str | None] = [None] * len(entries)
    pending: list[tuple[int, str, str, dict[str, str], int]] = []

    for pos, (idx, text) in enumerate(entries):
        if text in cache:
            results[pos] = cache[text]
            continue
        if not should_translate_text(text):
            result = apply_company_rules(text, company_seen)
            cache[text] = result
            results[pos] = result
            continue

        stats.translatable_lines += 1
        protected, placeholders = protect(text, source_terms, prefix=f"L{idx}")
        pending.append((pos, text, protected, placeholders, idx))

    for offset in range(0, len(pending), chunk_size):
        chunk = pending[offset : offset + chunk_size]
        protected_texts = [item[2] for item in chunk]
        translated_texts, _ = safe_translate_batch(translator, protected_texts, stats)

        for (pos, original, _protected, placeholders, _idx), translated in zip(chunk, translated_texts):
            restored = restore(translated, placeholders)
            restored = apply_company_rules(restored, company_seen)
            if restored != original:
                stats.translated_lines += 1
            cache[original] = restored
            results[pos] = restored

    return [result if result is not None else "" for result in results]


def translate_table_line(
    line: str,
    idx: int,
    translator: GoogleTranslator,
    source_terms: dict[str, str],
    stats: TranslationStats,
    cache: dict[str, str],
    company_seen: set[str],
) -> str:
    if TABLE_RULE_RE.match(line):
        return line
    cells = line.strip().strip("|").split("|")
    translated_cells = [
        f" {translate_text(cell.strip(), idx + offset, translator, source_terms, stats, cache, company_seen)} "
        for offset, cell in enumerate(cells)
    ]
    return "|" + "|".join(translated_cells) + "|"


def collect_qa_stats(lines: list[str], stats: TranslationStats) -> None:
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        has_cn = bool(re.search(r"[\u4e00-\u9fff]", stripped))
        has_latin = bool(re.search(r"[A-Za-zÀ-ÿ]", stripped))
        if has_latin and not has_cn and len(stats.latin_only_lines) < 20:
            stats.latin_only_lines.append((idx, stripped[:180]))
        if ("???" in stripped or "�" in stripped) and len(stats.garble_like_lines) < 20:
            stats.garble_like_lines.append((idx, stripped[:180]))


def translate_html_table_block(
    block: str,
    base_idx: int,
    translator: GoogleTranslator,
    source_terms: dict[str, str],
    stats: TranslationStats,
    cache: dict[str, str],
    company_seen: set[str],
) -> str:
    node_re = re.compile(r"(?P<open>>)(?P<text>[^<>]+?)(?P<close><)", re.S)

    def replace_node(match: re.Match[str]) -> str:
        text = match.group("text")
        stripped = text.strip()
        if not stripped:
            return match.group(0)
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()):]
        translated = translate_text(
            stripped, base_idx + match.start(), translator, source_terms, stats, cache, company_seen
        )
        return f">{leading}{translated}{trailing}<"

    return node_re.sub(replace_node, block)


def translate_lines(lines: list[str], source_lang: str, source_terms: dict[str, str]) -> tuple[list[str], TranslationStats]:
    translator = GoogleTranslator(source=source_lang, target="zh-CN")
    stats = TranslationStats()
    cache: dict[str, str] = {}
    company_seen: set[str] = set()
    output: list[str | None] = [None] * len(lines)
    pending_lines: list[tuple[int, str, str]] = []

    for idx, raw_line in enumerate(lines):
        stats.total_lines += 1
        if should_skip_line(raw_line):
            stats.skipped_noise_lines += 1
            output[idx] = None
            continue
        if not raw_line.strip():
            output[idx] = ""
            continue
        if is_markdown_table_line(raw_line):
            output[idx] = translate_table_line(
                raw_line, idx, translator, source_terms, stats, cache, company_seen
            )
            continue

        prefix, body = split_markdown_prefix(raw_line)
        pending_lines.append((idx, prefix, body))

    translated_pending = translate_text_batch(
        [(idx, body) for idx, _prefix, body in pending_lines],
        translator,
        source_terms,
        stats,
        cache,
        company_seen,
    )

    for (idx, prefix, body), translated in zip(pending_lines, translated_pending):
        output[idx] = prefix + translated if body else lines[idx]

    final_output = [line for line in output if line is not None]
    collect_qa_stats(final_output, stats)
    return final_output, stats


def translate_text_with_html_tables(raw_text: str, source_lang: str, source_terms: dict[str, str]) -> tuple[str, TranslationStats]:
    translator = GoogleTranslator(source=source_lang, target="zh-CN")
    stats = TranslationStats()
    cache: dict[str, str] = {}
    company_seen: set[str] = set()
    raw_text, removed_image_blocks = strip_image_blocks(raw_text)
    stats.skipped_noise_lines += removed_image_blocks
    pieces: list[str] = []
    last_end = 0
    line_offset = 0

    for match in HTML_TABLE_RE.finditer(raw_text):
        before = raw_text[last_end:match.start()]
        if before:
            translated_before, before_stats = translate_lines(before.splitlines(), source_lang, source_terms)
            stats.total_lines += before_stats.total_lines
            stats.translatable_lines += before_stats.translatable_lines
            stats.translated_lines += before_stats.translated_lines
            stats.skipped_noise_lines += before_stats.skipped_noise_lines
            stats.fallbacks += before_stats.fallbacks
            stats.latin_only_lines.extend(before_stats.latin_only_lines[: max(0, 20 - len(stats.latin_only_lines))])
            stats.garble_like_lines.extend(before_stats.garble_like_lines[: max(0, 20 - len(stats.garble_like_lines))])
            pieces.append("\n".join(translated_before))
            line_offset += before.count("\n") + 1

        block = match.group(0)
        stats.total_lines += block.count("\n") + 1
        pieces.append(
            translate_html_table_block(block, line_offset, translator, source_terms, stats, cache, company_seen)
        )
        line_offset += block.count("\n") + 1
        last_end = match.end()

    tail = raw_text[last_end:]
    if tail:
        translated_tail, tail_stats = translate_lines(tail.splitlines(), source_lang, source_terms)
        stats.total_lines += tail_stats.total_lines
        stats.translatable_lines += tail_stats.translatable_lines
        stats.translated_lines += tail_stats.translated_lines
        stats.skipped_noise_lines += tail_stats.skipped_noise_lines
        stats.fallbacks += tail_stats.fallbacks
        stats.latin_only_lines.extend(tail_stats.latin_only_lines[: max(0, 20 - len(stats.latin_only_lines))])
        stats.garble_like_lines.extend(tail_stats.garble_like_lines[: max(0, 20 - len(stats.garble_like_lines))])
        pieces.append("\n".join(translated_tail))

    output_text = "".join(pieces)
    final_lines = output_text.splitlines()
    stats.latin_only_lines = []
    stats.garble_like_lines = []
    collect_qa_stats(final_lines, stats)
    return output_text, stats


def main() -> None:
    _ensure_utf8_stdout()
    args = parse_args()
    input_path = resolve_path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    script_dir = Path(__file__).resolve().parent
    default_termbase = script_dir.parent / "references" / "termbase.md"
    source_terms = load_termbase(Path(args.termbase) if args.termbase else default_termbase) | SOURCE_TERM_MAP
    raw_text = load_input_text(input_path)
    translated_text, stats = translate_text_with_html_tables(raw_text, args.source, source_terms)

    output_path = Path(args.output)
    output_path.write_text(translated_text.rstrip("\n") + "\n", encoding="utf-8")

    if stats.translatable_lines and stats.translated_lines == 0:
        raise SystemExit("Translation failed: no translatable line produced a changed output.")

    print(
        f"summary total_lines={stats.total_lines} translatable={stats.translatable_lines} "
        f"translated={stats.translated_lines} skipped_noise={stats.skipped_noise_lines} "
        f"fallbacks={stats.fallbacks} latin_only={len(stats.latin_only_lines)} "
        f"garble_like={len(stats.garble_like_lines)}"
    )
    if stats.latin_only_lines:
        print("latin_only_samples=")
        for idx, text in stats.latin_only_lines[:10]:
            print(f"{idx}\t{text}")
    if stats.garble_like_lines:
        print("garble_like_samples=")
        for idx, text in stats.garble_like_lines[:10]:
            print(f"{idx}\t{text}")
    print(output_path)


if __name__ == "__main__":
    main()
