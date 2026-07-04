#!/usr/bin/env python3
"""
validate_citations.py — Verify all @citekeys in Markdown files exist in library.csl.json.

Usage:
    python validate_citations.py manuscript.md
    python validate_citations.py *.md
    python validate_citations.py --dir path/to/manuscripts/

Exit code 0 = all citations valid. Exit code 1 = missing citations found.
"""

import sys
import json
import re
import os
from pathlib import Path
from typing import Set, List, Tuple

BASE_DIR = Path(os.environ.get("CITATION_DIR", Path(__file__).parent))
LIBRARY_FILE = BASE_DIR / "library.csl.json"

# Matches @citekey, [@citekey], [@key1; @key2], [see @key, p. 5]
CITEKEY_RE = re.compile(r"@([\w][\w:./-]*\w)")

def load_library_keys() -> Set[str]:
    if not LIBRARY_FILE.exists():
        print(f"ERROR: Library not found at {LIBRARY_FILE}")
        print("       Run add_reference.py to add your first reference.")
        sys.exit(1)
    with open(LIBRARY_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {r["id"] for r in data}

def extract_citekeys(text: str) -> Set[str]:
    return set(CITEKEY_RE.findall(text))

def validate_file(path: Path, library_keys: Set[str]) -> Tuple[bool, int, List[str]]:
    """Returns (ok, n_keys, missing_keys)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    found = extract_citekeys(text)
    missing = sorted(found - library_keys)
    return (len(missing) == 0, len(found), missing)

def collect_files(args: List[str]) -> List[Path]:
    files = []
    i = 0
    while i < len(args):
        if args[i] == "--dir":
            i += 1
            d = Path(args[i]) if i < len(args) else Path(".")
            files.extend(sorted(d.rglob("*.md")))
        else:
            p = Path(args[i])
            if p.is_file():
                files.append(p)
            elif "*" in str(p):
                import glob
                files.extend(Path(f) for f in glob.glob(str(p)))
            else:
                print(f"Warning: {p} not found — skipping")
        i += 1
    return files

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    library_keys = load_library_keys()
    print(f"Library: {len(library_keys)} entries in {LIBRARY_FILE.name}\n")

    files = collect_files(sys.argv[1:])
    if not files:
        print("No Markdown files found.")
        sys.exit(0)

    all_ok = True
    for f in files:
        ok, n_keys, missing = validate_file(f, library_keys)
        if ok:
            tag = "OK  " if n_keys > 0 else "    "
            detail = f"{n_keys} citation(s) verified" if n_keys else "no citations"
            print(f"{tag} {f.name}: {detail}")
        else:
            all_ok = False
            print(f"FAIL {f.name}: {n_keys} citation(s) found, {len(missing)} missing:")
            for key in missing:
                print(f"       @{key}")

    print()
    if all_ok:
        print("All citations validated.")
    else:
        print("Validation FAILED — fix missing citekeys before rendering.")
        print("Add missing references with:  python add_reference.py <DOI>")
        sys.exit(1)

if __name__ == "__main__":
    main()
