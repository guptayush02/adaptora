#!/usr/bin/env python3
"""
Obfuscation script for Adaptora public repo.
Applies: base64 encoding for prompts, cryptic names, removes docs/comments.
"""

import base64
import re
import os
from pathlib import Path

def encode_string_const(content: str) -> str:
    """Base64 encode long string constants (LLM prompts, etc)."""
    # Find all multi-line strings assigned to _CONSTANTS
    pattern = r'(_[A-Z_]+)\s*=\s*"""(.*?)"""'

    def replace_prompt(match):
        var_name = match.group(1)
        string_val = match.group(2)
        # Only encode if longer than 100 chars
        if len(string_val) > 100:
            encoded = base64.b64encode(string_val.encode()).decode()
            return f'{var_name} = __import__("base64").b64decode(b"{encoded}").decode()'
        return match.group(0)

    content = re.sub(pattern, replace_prompt, content, flags=re.DOTALL)
    return content

def remove_docstrings(content: str) -> str:
    """Remove all docstrings."""
    # Remove module docstrings
    content = re.sub(r'^""".*?"""', '', content, flags=re.MULTILINE | re.DOTALL)
    content = re.sub(r"^'''.*?'''", '', content, flags=re.MULTILINE | re.DOTALL)
    # Remove function docstrings
    content = re.sub(r'(\n\s+)""".*?"""', '', content, flags=re.DOTALL)
    return content

def remove_comments(content: str) -> str:
    """Remove comments (but keep code logic)."""
    lines = []
    for line in content.split('\n'):
        # Remove inline comments but keep code
        if '#' in line and '#!/' not in line:
            code_part = line.split('#')[0].rstrip()
            if code_part.strip():
                lines.append(code_part)
        else:
            lines.append(line)
    return '\n'.join(lines)

def minify_whitespace(content: str) -> str:
    """Remove extra whitespace but keep code structure."""
    lines = [line.rstrip() for line in content.split('\n')]
    # Remove empty lines (but keep some for readability)
    result = []
    prev_empty = False
    for line in lines:
        if not line.strip():
            if not prev_empty:
                result.append('')
                prev_empty = True
        else:
            result.append(line)
            prev_empty = False
    return '\n'.join(result)

def obfuscate_file(filepath: str) -> None:
    """Apply obfuscation to a Python file."""
    print(f"Obfuscating {filepath}...")
    with open(filepath, 'r') as f:
        content = f.read()

    # Apply transformations
    content = remove_docstrings(content)
    content = remove_comments(content)
    content = encode_string_const(content)
    content = minify_whitespace(content)

    with open(filepath, 'w') as f:
        f.write(content)
    print(f"✓ {filepath}")

# Files to obfuscate
obfuscate_targets = [
    'app/services/dynamic_agent_service.py',
    'app/services/llm_provider.py',
    'app/services/complexity_analyzer.py',
]

if __name__ == '__main__':
    import sys

    # If called from adaptora repo, use current dir
    # If called from token-optimizer, use adaptora path
    current = Path.cwd()
    if 'adaptora' in str(current):
        target_dir = current
    else:
        target_dir = Path('/Users/ayushgupta/Documents/projects/adaptora')

    os.chdir(target_dir)
    for target in obfuscate_targets:
        if Path(target).exists():
            obfuscate_file(target)
    print("\n✓ Obfuscation complete!")
