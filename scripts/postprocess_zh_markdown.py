from __future__ import annotations

import argparse
import re
from pathlib import Path


EXACT_REPLACEMENTS = {
    "规格": "招标文件",
    "概括": "目录",
    "概要": "总目录",
    "附录": "附件",
    "解除限制标准": "否决性标准",
    "技术规格书/招标技术要求": "招标文件",
}

SUBSTRING_REPLACEMENTS = {
    "限制性国内和国际招标": "限制性国内及国际招标",
    "技术规格书": "招标文件",
    "招标技术要求": "招标文件",
    "财务标书": "商务标书",
    "验证工作流": "验证工作流",
    "候选人s": "候选人",
    "投标/报价s": "投标文件",
    "投标/报价 ": "投标文件 ",
    "投标/报价征集": "招标",
    "应聘/候选": "候选",
}

REGEX_REPLACEMENTS = [
    (re.compile(r"规格(?=的目的)"), "招标文件"),
    (re.compile(r"第(\s*\d+\s*条)：规格"), r"第\1条：招标文件"),
    (re.compile(r"ARTICLE\s*(\d+)\s*[：:]"), r"第 \1 条："),
]


def normalize_line(line: str) -> str:
    stripped = line.strip()
    if stripped in EXACT_REPLACEMENTS:
        leading = line[: len(line) - len(line.lstrip())]
        trailing = line[len(line.rstrip()):]
        line = f"{leading}{EXACT_REPLACEMENTS[stripped]}{trailing}"
    for source, target in SUBSTRING_REPLACEMENTS.items():
        line = line.replace(source, target)
    for pattern, replacement in REGEX_REPLACEMENTS:
        line = pattern.sub(replacement, line)
    return line


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    lines = input_path.read_text(encoding="utf-8").splitlines()
    output = "\n".join(normalize_line(line) for line in lines) + "\n"
    Path(args.output).write_text(output, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
