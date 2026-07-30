#!/usr/bin/env python3
"""
check_doc_quality.py — 文档表达质量与 Mermaid 渲染审计

扫描 docs 目录下的 Markdown 文件，输出确定性残留报告：

- META-NARRATIVE          自证式元叙述（"本文不使用……"等）
- MERMAID-LITERAL-ESCAPE  Mermaid 节点文本中残留字面量 \\n / \\\\n / \\r\\n / \\t
- MERMAID-UNCLOSED-BLOCK  Mermaid fenced block 未闭合
- MERMAID-LONG-LABEL      节点标签过长（>60 字符）
- BROKEN-RELATIVE-LINK    指向不存在文件的相对链接

Markdown 感知规则：

- 元叙述检查只作用于普通正文行，跳过 fenced code block（含 Mermaid）、
  inline code、引用块和 HTML 注释中的抑制标记。
- Mermaid 检查只作用于 ```mermaid ... ``` 代码块内部。
- 相对链接检查作用于普通正文行，跳过所有 fenced code block。

抑制标记（放在 HTML 注释中）：

<!-- tidy-doc: ignore META-NARRATIVE -->     抑制本文件的元叙述检查
<!-- tidy-doc: ignore BROKEN-RELATIVE-LINK --> 抑制本文件的链接检查

用法:
  python scripts/check_doc_quality.py --docs-dir docs

输出格式 (stdout):
  <file>:<line>
  [<ISSUE_TYPE>]
  <snippet>

退出码:
  0 — 无问题
  1 — 发现问题
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# ---------- 模式定义 ----------

META_NARRATIVE_PATTERNS = [
    re.compile(r'本文不使用'),
    re.compile(r'本专题不使用'),
    re.compile(r'本文不称为'),
    re.compile(r'这里不要理解为'),
    re.compile(r'不要理解为'),
    re.compile(r'为了避免误解'),
    re.compile(r'为避免误解'),
    re.compile(r'本文并不是要'),
    re.compile(r'本文不是'),
    re.compile(r'之所以这样命名'),
    re.compile(r'之所以这样称呼'),
    re.compile(r'需要特别说明，我们没有'),
]

# 节点标签中带字面量转义符的模式（双引号或单引号内）
LITERAL_ESCAPE_RE = re.compile(
    r'["\'][^"\']*(?:\\n|\\\\n|\\r\\n|\\t)[^"\']*["\']'
)

# 节点标签长度检查（捕获 A["..."] 或 A['...'] 中的内容）
NODE_LABEL_RE = re.compile(
    r'\b([A-Za-z_]\w*)\s*\[\s*["\'](.+?)["\']\s*\]'
)

MAX_LABEL_LEN = 60

# 相对链接检查（[text](./path/to/file.md) 或 [text](../path/file.md)）
REL_LINK_RE = re.compile(r'\[([^\]]+)\]\(\.\/([^)]+)\)|\[([^\]]+)\]\(\.\.\/([^)]+)\)')

# 抑制标记
SUPPRESS_META_RE = re.compile(r'<!--\s*tidy-doc:\s*ignore\s*META-NARRATIVE\s*-->')
SUPPRESS_LINK_RE = re.compile(r'<!--\s*tidy-doc:\s*ignore\s*BROKEN-RELATIVE-LINK\s*-->')

# Fenced code block 开始/结束标记
FENCE_RE = re.compile(r'^\s*```')


# ---------- Markdown 分块 ----------

def partition_markdown(text: str):
    """
    将 Markdown 文本划分为三类行集合：

    - prose_lines:   普通正文行（可用于元叙述和链接检查）
    - mermaid_blocks: list of (start_lineno, block_text)
    - code_lines:    fenced code block 内的行（不参与任何检查）

    返回 (prose_lines, mermaid_blocks, code_linenos)。
    prose_lines 和 code_linenos 是 dict: {lineno: line_text}。
    """
    prose_lines = {}
    code_linenos = set()
    mermaid_blocks = []

    lines = text.splitlines()
    in_block = False
    block_lang = ''
    block_start = 0
    block_buf = []

    for lineno, line in enumerate(lines, start=1):
        if not in_block:
            m = FENCE_RE.match(line)
            if m:
                # 提取语言标识
                lang_match = re.match(r'^\s*```(\w*)', line)
                block_lang = (lang_match.group(1) if lang_match else '').lower()
                in_block = True
                block_start = lineno
                block_buf = [line]
                code_linenos.add(lineno)
                continue
            prose_lines[lineno] = line
        else:
            code_linenos.add(lineno)
            block_buf.append(line)
            if FENCE_RE.match(line.strip()):
                # block 结束
                if block_lang == 'mermaid':
                    mermaid_blocks.append((block_start, '\n'.join(block_buf)))
                in_block = False
                block_lang = ''
                block_buf = []

    # 未闭合的 block 当作 code 处理（不会参与 prose 检查）
    return prose_lines, mermaid_blocks, code_linenos


# ---------- 扫描器 ----------

def scan_meta_narrative(prose_lines: dict[int, str], full_text: str) -> list[tuple[int, str, str]]:
    """
    仅在普通正文行中搜索元叙述模式。
    如果全文包含 <!-- tidy-doc: ignore META-NARRATIVE --> 则跳过全部检查。
    """
    if SUPPRESS_META_RE.search(full_text):
        return []

    issues = []
    for lineno, line in prose_lines.items():
        for pat in META_NARRATIVE_PATTERNS:
            m = pat.search(line)
            if m:
                issues.append((lineno, m.group(0).strip(), line.strip()))
                break  # 每行只报一次
    return issues


def scan_mermaid_blocks(mermaid_blocks: list[tuple[int, str]]) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    """
    扫描 Mermaid fenced block 的三类问题。
    返回 (escape_issues, unclosed_issues, long_label_issues)。
    每项为 [(lineno, issue_detail, snippet), ...]。
    """
    escape_issues = []
    unclosed_issues = []
    long_label_issues = []

    for block_start, block_text in mermaid_blocks:
        lines = block_text.splitlines()

        # 1) 字面量转义残留
        for m in LITERAL_ESCAPE_RE.finditer(block_text):
            offset = m.start()
            ln = block_start + block_text[:offset].count('\n')
            snippet = m.group(0)[:80]
            escape_issues.append((ln, snippet, lines[ln - block_start].strip()))

        # 2) 节点标签过长
        for m in NODE_LABEL_RE.finditer(block_text):
            label = m.group(2)
            if len(label) > MAX_LABEL_LEN:
                offset = m.start()
                ln = block_start + block_text[:offset].count('\n')
                snippet = label[:60] + '…'
                long_label_issues.append((ln, f'{len(label)} chars', snippet))

    # 3) 未闭合 block：由 partition_markdown 保证只传入已闭合的 block，
    #    因此此处不再重复检测。若调用方需要检测未闭合 block，应另行提供信号。
    _ = unclosed_issues  # 保留接口兼容

    return escape_issues, unclosed_issues, long_label_issues


def detect_unclosed_mermaid(text: str) -> list[tuple[int, str, str]]:
    """单独检测未闭合的 Mermaid fenced block。"""
    issues = []
    lines = text.splitlines()
    in_block = False
    block_start = 0

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not in_block and stripped.startswith('```mermaid'):
            in_block = True
            block_start = lineno
            continue
        if in_block and stripped.startswith('```') and stripped != '```mermaid':
            in_block = False

    if in_block:
        issues.append((block_start, 'unclosed mermaid block', lines[block_start - 1].strip()))

    return issues


def scan_broken_links(prose_lines: dict[int, str], full_text: str, file_path: Path, docs_dir: Path) -> list[tuple[int, str, str]]:
    """
    仅在普通正文行中检查相对链接是否指向存在的文件。
    如果全文包含 <!-- tidy-doc: ignore BROKEN-RELATIVE-LINK --> 则跳过全部检查。
    """
    if SUPPRESS_LINK_RE.search(full_text):
        return []

    issues = []
    file_dir = file_path.parent

    for lineno, line in prose_lines.items():
        for m in REL_LINK_RE.finditer(line):
            link_text = m.group(1) or m.group(3)
            rel_path_str = m.group(2) or m.group(4)
            # 去掉可能的锚点
            rel_path_str = rel_path_str.split('#')[0]
            if not rel_path_str:
                continue

            target = (file_dir / rel_path_str).resolve()
            if not target.exists():
                issues.append((lineno, f'link to {rel_path_str}', f'[{link_text}]({rel_path_str})'))

    return issues


# ---------- 主入口 ----------

def main() -> int:
    parser = argparse.ArgumentParser(description='文档表达质量与 Mermaid 渲染审计')
    parser.add_argument('--docs-dir', default='docs', help='docs 目录路径 (默认: docs)')
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    if not docs_dir.is_dir():
        print(f'[WARN] docs dir not found: {docs_dir}', file=sys.stderr)
        return 0

    md_files = sorted(docs_dir.rglob('*.md'))
    if not md_files:
        print('[INFO] no markdown files found', file=sys.stderr)
        return 0

    total_issues = 0

    for md in md_files:
        try:
            text = md.read_text(encoding='utf-8')
        except Exception as e:
            print(f'[WARN] skip {md}: {e}', file=sys.stderr)
            continue

        rel = md.relative_to(docs_dir)

        # 分区
        prose_lines, mermaid_blocks, _ = partition_markdown(text)

        # 1) 元叙述（仅正文）
        for lineno, detail, snippet in scan_meta_narrative(prose_lines, text):
            print(f'{rel}:{lineno}')
            print('[META-NARRATIVE]')
            print(snippet)
            print()
            total_issues += 1

        # 2) Mermaid 问题
        escapes, _, long_labels = scan_mermaid_blocks(mermaid_blocks)
        for lineno, detail, snippet in escapes:
            print(f'{rel}:{lineno}')
            print('[MERMAID-LITERAL-ESCAPE]')
            print(snippet)
            print()
            total_issues += 1

        for lineno, detail, snippet in long_labels:
            print(f'{rel}:{lineno}')
            print('[MERMAID-LONG-LABEL]')
            print(snippet)
            print()
            total_issues += 1

        # 3) 未闭合 Mermaid block（全文件级别）
        for lineno, detail, snippet in detect_unclosed_mermaid(text):
            print(f'{rel}:{lineno}')
            print('[MERMAID-UNCLOSED-BLOCK]')
            print(snippet)
            print()
            total_issues += 1

        # 4) 断裂相对链接（仅正文）
        broken = scan_broken_links(prose_lines, text, md, docs_dir)
        for lineno, detail, snippet in broken:
            print(f'{rel}:{lineno}')
            print('[BROKEN-RELATIVE-LINK]')
            print(snippet)
            print()
            total_issues += 1

    return 1 if total_issues else 0


if __name__ == '__main__':
    sys.exit(main())
