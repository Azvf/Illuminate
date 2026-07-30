#!/usr/bin/env python3
"""
check_doc_quality.py — 文档表达质量与 Mermaid 渲染审计

扫描 docs 目录下的 Markdown 文件，输出确定性残留报告：

- META-NARRATIVE          自证式元叙述（"本文不使用……"等）
- MERMAID-LITERAL-ESCAPE  Mermaid 节点文本中残留字面量 \n / \\n / \r\n / \t
- MERMAID-UNCLOSED-BLOCK  Mermaid fenced block 未闭合
- MERMAID-LONG-LABEL      节点标签过长（>60 字符）
- BROKEN-RELATIVE-LINK    指向不存在文件的相对链接

用法:
  python packs/core/skills/tidy-doc/scripts/check_doc_quality.py [--docs-dir PATH]

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
import os
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

# 匹配 Mermaid fenced block: ```mermaid ... ```
MERMAID_BLOCK_RE = re.compile(r'^```mermaid\s*$', re.MULTILINE)

# 节点标签中带字面量转义符的模式（在引号内）
LITERAL_ESCAPE_RE = re.compile(
    r'"[^"]*(?:\\n|\\\\n|\\r\\n|\\t)[^"]*"'
)

# 节点标签长度检查（捕获 A["..."] 或 A['...'] 中的内容）
NODE_LABEL_RE = re.compile(
    r'\b([A-Za-z_]\w*)\s*\[\s*["\'](.+?)["\']\s*\]'
)

MAX_LABEL_LEN = 60

# 相对链接检查（[text](./path/to/file.md) 或 [text](../path/file.md)）
REL_LINK_RE = re.compile(r'\[([^\]]+)\]\(\.\/([^)]+)\)|\[([^\]]+)\]\(\.\.\/([^)]+)\)')


# ---------- 扫描器 ----------

def scan_meta_narrative(path: Path, text: str) -> list[tuple[int, str, str]]:
    """返回 [(lineno, pattern_match, line_text), ...]"""
    issues = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pat in META_NARRATIVE_PATTERNS:
            m = pat.search(line)
            if m:
                issues.append((lineno, m.group(0).strip(), line.strip()))
                break  # 每行只报一次
    return issues


def scan_mermaid_blocks(path: Path, text: str) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    """
    扫描 Mermaid fenced block 的三类问题。
    返回 (escape_issues, unclosed_issues, long_label_issues)。
    每项为 [(lineno, issue_detail, snippet), ...]。
    """
    escape_issues = []
    unclosed_issues = []
    long_label_issues = []

    lines = text.splitlines()
    in_block = False
    block_start = 0
    block_lines = []

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()

        if not in_block and stripped.startswith('```mermaid'):
            in_block = True
            block_start = lineno
            block_lines = [line]
            continue

        if in_block:
            block_lines.append(line)
            if stripped.startswith('```') and stripped != '```mermaid':
                # block 结束
                block_text = '\n'.join(block_lines)

                # 1) 字面量转义残留
                for m in LITERAL_ESCAPE_RE.finditer(block_text):
                    # 计算行号
                    offset = m.start()
                    ln = block_start + block_text[:offset].count('\n')
                    snippet = m.group(0)[:80]
                    escape_issues.append((ln, snippet, block_lines[ln - block_start].strip()))

                # 2) 节点标签过长
                for m in NODE_LABEL_RE.finditer(block_text):
                    label = m.group(2)
                    if len(label) > MAX_LABEL_LEN:
                        offset = m.start()
                        ln = block_start + block_text[:offset].count('\n')
                        snippet = label[:60] + '…'
                        long_label_issues.append((ln, f'{len(label)} chars', snippet))

                in_block = False
                block_lines = []

    # 3) 未闭合 block
    if in_block:
        unclosed_issues.append((block_start, 'unclosed mermaid block', lines[block_start - 1].strip()))

    return escape_issues, unclosed_issues, long_label_issues


def scan_broken_links(path: Path, text: str, docs_dir: Path) -> list[tuple[int, str, str]]:
    """检查相对链接是否指向存在的文件。"""
    issues = []
    file_dir = path.parent

    for m in REL_LINK_RE.finditer(text):
        link_text = m.group(1) or m.group(3)
        rel_path_str = m.group(2) or m.group(4)
        # 去掉可能的锚点
        rel_path_str = rel_path_str.split('#')[0]
        if not rel_path_str:
            continue

        target = (file_dir / rel_path_str).resolve()
        if not target.exists():
            lineno = text[:m.start()].count('\n') + 1
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

        # 1) 元叙述
        for lineno, detail, snippet in scan_meta_narrative(md, text):
            print(f'{rel}:{lineno}')
            print('[META-NARRATIVE]')
            print(snippet)
            print()
            total_issues += 1

        # 2) Mermaid 三类问题
        escapes, unclosed, long_labels = scan_mermaid_blocks(md, text)
        for lineno, detail, snippet in escapes:
            print(f'{rel}:{lineno}')
            print('[MERMAID-LITERAL-ESCAPE]')
            print(snippet)
            print()
            total_issues += 1

        for lineno, detail, snippet in unclosed:
            print(f'{rel}:{lineno}')
            print('[MERMAID-UNCLOSED-BLOCK]')
            print(snippet)
            print()
            total_issues += 1

        for lineno, detail, snippet in long_labels:
            print(f'{rel}:{lineno}')
            print('[MERMAID-LONG-LABEL]')
            print(snippet)
            print()
            total_issues += 1

        # 3) 断裂相对链接
        broken = scan_broken_links(md, text, docs_dir)
        for lineno, detail, snippet in broken:
            print(f'{rel}:{lineno}')
            print('[BROKEN-RELATIVE-LINK]')
            print(snippet)
            print()
            total_issues += 1

    return 1 if total_issues else 0


if __name__ == '__main__':
    sys.exit(main())
