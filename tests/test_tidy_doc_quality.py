"""
tests/test_tidy_doc_quality.py

针对 tidy-doc 文档质量扫描器的单元测试。

覆盖：
- 命中"本专题不使用……"等元叙述
- 保留正常的"X 不负责 Y"业务否定句
- 命中 Mermaid 中的 \\n 和 \\\\n
- 不误报 <br/>
- 命中未闭合 Mermaid block
- 正确与错误的相对链接
- 退出码 0 / 1
- fenced code block 内的元叙述不误报
- 抑制标记生效
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'packs' / 'core' / 'skills' / 'tidy-doc' / 'scripts'))

from check_doc_quality import (
    META_NARRATIVE_PATTERNS,
    detect_unclosed_mermaid,
    partition_markdown,
    scan_broken_links,
    scan_meta_narrative,
    scan_mermaid_blocks,
)


# ---------- 辅助 ----------

def run_scan(md_content: str, docs_dir: Path) -> tuple[int, str]:
    """把 md_content 写入临时 docs 目录并运行主程序，返回 (exit_code, stdout)。"""
    import subprocess

    script = Path(__file__).resolve().parent.parent / 'packs' / 'core' / 'skills' / 'tidy-doc' / 'scripts' / 'check_doc_quality.py'

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'docs'
        d.mkdir()
        (d / 'test.md').write_text(md_content, encoding='utf-8')

        result = subprocess.run(
            [sys.executable, str(script), '--docs-dir', str(d)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode, result.stdout


# ---------- partition_markdown ----------

def test_partition_simple_prose():
    text = 'Hello\nWorld\n'
    prose, mblocks, code = partition_markdown(text)
    assert prose == {1: 'Hello', 2: 'World'}
    assert mblocks == []
    assert code == set()


def test_partition_skips_fenced_code():
    text = 'intro\n```python\nprint("hi")\n```\noutro\n'
    prose, mblocks, code = partition_markdown(text)
    assert prose == {1: 'intro', 5: 'outro'}
    assert mblocks == []
    assert code == {2, 3, 4}


def test_partition_mermaid_block():
    text = 'before\n```mermaid\nflowchart LR\nA-->B\n```\nafter\n'
    prose, mblocks, code = partition_markdown(text)
    assert prose == {1: 'before', 6: 'after'}
    assert len(mblocks) == 1
    start, block = mblocks[0]
    assert start == 2
    assert 'flowchart LR' in block
    assert code == {2, 3, 4, 5}


def test_partition_inline_code_preserved():
    text = 'Use `grep -rn "本文不使用"` to find issues.\n'
    prose, _, _ = partition_markdown(text)
    # inline code 行仍属于 prose（当前实现不做 inline 级排除）
    assert 1 in prose


# ---------- scan_meta_narrative ----------

def test_hits_meta_narrative_this_special_topic():
    prose = {1: '本专题不使用"TGPA 切后台保活方案"作为名称。'}
    issues = scan_meta_narrative(prose, '')
    assert len(issues) == 1
    assert issues[0][1] == '本专题不使用'


def test_hits_meta_narrative_avoid_misunderstanding():
    prose = {1: '为了避免误解，这里说明一下。'}
    issues = scan_meta_narrative(prose, '')
    assert len(issues) == 1
    assert issues[0][1] == '为了避免误解'


def test_hits_meta_narrative_why_named():
    prose = {1: '之所以这样命名，是因为历史原因。'}
    issues = scan_meta_narrative(prose, '')
    assert len(issues) == 1
    assert issues[0][1] == '之所以这样命名'


def test_business_negative_not_matched():
    """业务否定句不应被误报。"""
    prose = {1: 'TGPA 不负责分片写入。'}
    issues = scan_meta_narrative(prose, '')
    assert issues == []


def test_normal_prose_not_matched():
    prose = {1: 'TGPA 负责预下载路径和更新通知。'}
    issues = scan_meta_narrative(prose, '')
    assert issues == []


def test_suppress_meta_narrative_via_comment():
    prose = {1: '本专题不使用旧名称。'}
    full = '<!-- tidy-doc: ignore META-NARRATIVE -->\n本专题不使用旧名称。'
    issues = scan_meta_narrative(prose, full)
    assert issues == []


def test_code_block_meta_narrative_excluded_by_partition():
    """fenced code 内的元叙述应被分区逻辑排除。"""
    text = '正常正文。\n```python\n# 本文不使用旧名称\n```\n继续正文。\n'
    prose, _, _ = partition_markdown(text)
    # code 行不在 prose 中
    for line in prose.values():
        assert '本文不使用' not in line
    issues = scan_meta_narrative(prose, text)
    assert issues == []


# ---------- scan_mermaid_blocks ----------

def test_mermaid_literal_backslash_n():
    block = ['flowchart LR', 'A["FUpdateServiceRunnable\\n启动循环"]']
    text = '\n'.join(block)
    escapes, _, _ = scan_mermaid_blocks([(1, text)])
    assert len(escapes) == 1
    assert '\\n' in escapes[0][1]


def test_mermaid_double_escaped_backslash_n():
    block = ['flowchart LR', 'A["FUpdateServiceRunnable\\\\n启动循环"]']
    text = '\n'.join(block)
    escapes, _, _ = scan_mermaid_blocks([(1, text)])
    assert len(escapes) == 1
    assert '\\\\n' in escapes[0][1]


def test_mermaid_br_tag_not_reported():
    """<br/> 不应被误报。"""
    block = ['flowchart LR', 'A["第一行<br/>第二行"]']
    text = '\n'.join(block)
    escapes, _, _ = scan_mermaid_blocks([(1, text)])
    assert escapes == []


def test_mermaid_single_quoted_label_escape():
    block = ["flowchart LR", "A['Task\\nDesc']"]
    text = '\n'.join(block)
    escapes, _, _ = scan_mermaid_blocks([(1, text)])
    assert len(escapes) == 1


def test_mermaid_long_label():
    # 标签长度 > 60 阈值（约 72 字符，保留中文以覆盖非 ASCII 场景），应触发 MERMAID-LONG-LABEL
    block = ['flowchart LR', 'A["这是一个非常非常长的节点标签，超过六十字符限制用于测试长标签检测功能是否正常触发这是一个非常非常长的节点标签，超过六十字符限制用于测试长标签检测"]']
    text = '\n'.join(block)
    _, _, long_labels = scan_mermaid_blocks([(1, text)])
    assert len(long_labels) == 1


def test_mermaid_long_label_boundary():
    """边界：MAX_LABEL_LEN=60 用 > 判定，60 字符不触发、61 字符触发。"""
    label_60 = '长' * 60
    label_61 = '长' * 61
    _, _, long_60 = scan_mermaid_blocks([(1, f'A["{label_60}"]')])
    _, _, long_61 = scan_mermaid_blocks([(1, f'A["{label_61}"]')])
    assert long_60 == []
    assert len(long_61) == 1


def test_mermaid_clean_block():
    block = ['flowchart LR', 'A["正常节点"]', 'B["另一节点"]', 'A --> B']
    text = '\n'.join(block)
    escapes, _, long_labels = scan_mermaid_blocks([(1, text)])
    assert escapes == []
    assert long_labels == []


# ---------- detect_unclosed_mermaid ----------

def test_unclosed_mermaid_detected():
    text = 'intro\n```mermaid\nflowchart LR\nA-->B\n'
    issues = detect_unclosed_mermaid(text)
    assert len(issues) == 1
    assert issues[0][0] == 2  # 起始行号


def test_closed_mermaid_not_reported():
    text = 'intro\n```mermaid\nflowchart LR\nA-->B\n```\noutro\n'
    issues = detect_unclosed_mermaid(text)
    assert issues == []


# ---------- scan_broken_links ----------

def test_broken_relative_link():
    prose = {1: '详见 [指南](./NonExistent.md)。'}
    fake_file = Path('/fake/docs/test.md')
    fake_docs = Path('/fake/docs')
    issues = scan_broken_links(prose, '', fake_file, fake_docs)
    assert len(issues) == 1
    assert 'NonExistent.md' in issues[0][1]


def test_valid_relative_link_not_reported(tmp_path: Path):
    """存在目标的相对链接不应被报告。"""
    (tmp_path / 'target.md').write_text('x', encoding='utf-8')
    prose = {1: f'详见 [指南](./target.md)。'}
    issues = scan_broken_links(prose, '', tmp_path / 'src.md', tmp_path)
    assert issues == []


def test_link_in_code_block_excluded():
    text = '正文。\n```markdown\n[坏链](./Missing.md)\n```\n结尾。\n'
    prose, _, _ = partition_markdown(text)
    # code 行不在 prose 中
    for line in prose.values():
        assert 'Missing.md' not in line
    fake_file = Path('/fake/docs/test.md')
    fake_docs = Path('/fake/docs')
    issues = scan_broken_links(prose, '', fake_file, fake_docs)
    assert issues == []


def test_suppress_broken_link_via_comment(tmp_path: Path):
    prose = {1: '详见 [坏链](./Missing.md)。'}
    full = '<!-- tidy-doc: ignore BROKEN-RELATIVE-LINK -->\n详见 [坏链](./Missing.md)。'
    fake_file = Path('/fake/docs/test.md')
    fake_docs = Path('/fake/docs')
    issues = scan_broken_links(prose, full, fake_file, fake_docs)
    assert issues == []


# ---------- 端到端 exit code ----------

def test_exit_code_zero_on_clean():
    clean = '## 正常文档\n\nTGPA 负责更新通知。\n'
    code, out = run_scan(clean, Path('.'))
    assert code == 0
    assert out.strip() == ''


def test_exit_code_one_on_meta_narrative():
    dirty = '## 标题\n\n本专题不使用旧名称。\n'
    code, out = run_scan(dirty, Path('.'))
    assert code == 1
    assert 'META-NARRATIVE' in out
    assert '本专题不使用' in out


def test_exit_code_one_on_mermaid_escape():
    dirty = '## 标题\n\n```mermaid\nflowchart LR\nA["Task\\nDesc"]\n```\n'
    code, out = run_scan(dirty, Path('.'))
    assert code == 1
    assert 'MERMAID-LITERAL-ESCAPE' in out


def test_exit_code_one_on_unclosed_mermaid():
    dirty = '## 标题\n\n```mermaid\nflowchart LR\nA-->B\n'
    code, out = run_scan(dirty, Path('.'))
    assert code == 1
    assert 'MERMAID-UNCLOSED-BLOCK' in out


def test_code_block_does_not_trigger_meta_narrative():
    """fenced code 中的元叙述不应触发报告。"""
    mixed = '''## 标题

正常正文。

```python
# 本文不使用旧名称
```

继续正文。
'''
    code, out = run_scan(mixed, Path('.'))
    assert code == 0
    assert 'META-NARRATIVE' not in out


def test_inline_example_with_meta_phrase_not_reported_when_in_code_fence():
    """反例说明放在代码块中不应误报。"""
    mixed = '''## 规则示例

不推荐写法：

```text
本文不使用某名称。
```

推荐写法：

```text
TGPA 是桥接层。
```
'''
    code, out = run_scan(mixed, Path('.'))
    assert code == 0
    assert 'META-NARRATIVE' not in out
