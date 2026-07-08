#!/usr/bin/env python3
"""Fail if any module under zotvault/ imports a third-party package.

The zero-runtime-dependency invariant is load-bearing (one-command install,
no supply chain). This guard keeps it honest in CI.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "zotvault"

# stdlib module names ZotVault is allowed to import (top-level only).
STDLIB = {
    "__future__", "argparse", "array", "collections", "dataclasses", "datetime",
    "functools", "http", "io", "json", "logging", "math", "os", "pathlib",
    "platform", "re", "shutil", "signal", "socket", "sqlite3", "subprocess",
    "sys", "tempfile", "threading", "time", "typing", "urllib", "uuid",
    "xml", "zipfile", "hashlib", "base64", "html", "email", "contextlib",
    "itertools", "tomllib", "http.server", "http.cookiejar", "webbrowser",
}

# Optional-extra imports allowed ONLY in these files (guarded by try/ImportError
# and shipped as extras — the core stays zero-dependency).
OPTIONAL = {
    "zotvault/tray.py": {"pystray", "PIL"},
}

bad = []
for py in sorted(PKG.rglob("*.py")):
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import within the package
                continue
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        rel = str(py.relative_to(ROOT))
        for n in names:
            if n and n != "zotvault" and n not in STDLIB and n not in OPTIONAL.get(rel, set()):
                bad.append("{}:{} imports '{}'".format(rel, node.lineno, n))

if bad:
    print("Third-party imports found (violates stdlib-only invariant):")
    print("\n".join("  " + b for b in bad))
    sys.exit(1)
print("stdlib-only: OK ({} modules checked)".format(len(list(PKG.rglob('*.py')))))
