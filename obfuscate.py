#!/usr/bin/env python3
"""
Obfuscation script for Adaptora public repo.

Applies, in order:
  1. base64-encode long string constants (the LLM prompts — the real IP)
  2. safely strip comments + docstrings via the `tokenize` module
     (NOT naive '#' splitting — that corrupts regex/strings containing '#')
  3. collapse blank lines

Every output file is validated with compile() so a broken obfuscation
can never be shipped.
"""

import base64
import io
import os
import re
import tokenize
from pathlib import Path


def encode_string_const(content: str) -> str:
    """Base64-encode long triple-quoted constants assigned to _UPPER names."""
    pattern = r'(_[A-Z0-9_]+)\s*=\s*"""(.*?)"""'

    def replace_prompt(match):
        var_name = match.group(1)
        string_val = match.group(2)
        if len(string_val) > 100:
            encoded = base64.b64encode(string_val.encode()).decode()
            return f'{var_name} = __import__("base64").b64decode("{encoded}").decode()'
        return match.group(0)

    return re.sub(pattern, replace_prompt, content, flags=re.DOTALL)


def strip_comments_and_docstrings(source: str) -> str:
    """Remove comments and docstrings using tokenize (string-safe).

    A '#' inside a string is part of a STRING token, never a COMMENT token,
    so this never truncates regexes or string literals — the bug that the
    old naive split('#') implementation had.
    """
    out = []
    prev_toktype = tokenize.INDENT
    last_lineno = -1
    last_col = 0

    tokgen = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok_type, tok_str, (sline, scol), (eline, ecol), _ in tokgen:
        if sline > last_lineno:
            last_col = 0
        if scol > last_col:
            out.append(" " * (scol - last_col))

        if tok_type == tokenize.COMMENT:
            pass  # drop comments
        elif tok_type == tokenize.STRING:
            # A STRING that directly follows INDENT/NEWLINE/NL is a docstring
            # (bare string statement) → drop it. Anything after an operator,
            # name, '(' etc. is a real value → keep it.
            if prev_toktype in (tokenize.INDENT, tokenize.NEWLINE, tokenize.NL):
                pass
            else:
                out.append(tok_str)
        else:
            out.append(tok_str)

        prev_toktype = tok_type
        last_col = ecol
        last_lineno = eline

    return "".join(out)


def collapse_blank_lines(content: str) -> str:
    result = []
    prev_empty = False
    for line in content.split("\n"):
        if not line.strip():
            if not prev_empty:
                result.append("")
                prev_empty = True
        else:
            result.append(line.rstrip())
            prev_empty = False
    return "\n".join(result)


def obfuscate_file(filepath: str) -> None:
    print(f"Obfuscating {filepath}...")
    with open(filepath, "r") as f:
        original = f.read()

    content = encode_string_const(original)
    content = strip_comments_and_docstrings(content)
    content = collapse_blank_lines(content)

    # SAFETY: never write a file that won't import. Fall back to the
    # base64-only version (no token stripping) if something went wrong.
    try:
        compile(content, filepath, "exec")
    except SyntaxError as exc:
        print(f"  ⚠️  token-strip produced invalid Python ({exc}); "
              f"falling back to base64-only obfuscation")
        content = collapse_blank_lines(encode_string_const(original))
        compile(content, filepath, "exec")  # this must succeed

    with open(filepath, "w") as f:
        f.write(content)
    print(f"  ✓ {filepath} (valid)")


obfuscate_targets = [
    "app/services/dynamic_agent_service.py",
    "app/services/llm_provider.py",
    "app/services/complexity_analyzer.py",
]

if __name__ == "__main__":
    current = Path.cwd()
    if "adaptora" in str(current):
        target_dir = current
    else:
        target_dir = Path("/Users/ayushgupta/Documents/projects/adaptora")

    os.chdir(target_dir)
    for target in obfuscate_targets:
        if Path(target).exists():
            obfuscate_file(target)
    print("\n✓ Obfuscation complete!")
