#!/usr/bin/env python3
"""Cross-platform bootstrap for Test Planner scripts (Windows/Linux/macOS).

Creates an isolated venv in .test-agent/.venv and installs dependencies
(jsonschema). Idempotent. No global installs.

Usage:
    python .github/agents/common/scripts/setup.py

After bootstrap, use the venv interpreter:
    Windows:      .test-agent\\.venv\\Scripts\\python.exe
    Linux/macOS:  .test-agent/.venv/bin/python
"""

import os
import subprocess
import sys
import venv
from pathlib import Path

MIN_PY = (3, 9)
DEPS = ["jsonschema"]


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def main() -> int:
    if sys.version_info < MIN_PY:
        print(f"ERROR: Python {MIN_PY[0]}.{MIN_PY[1]}+ required, "
              f"found {sys.version.split()[0]}.", file=sys.stderr)
        return 1

    # repo root = 4 poziomy nad tym plikiem (.github/agents/common/scripts/)
    repo_root = Path(__file__).resolve().parents[4]
    venv_dir = repo_root / ".test-agent" / ".venv"
    py = venv_python(venv_dir)

    if not py.exists():
        print(f"Creating venv at {venv_dir} ...")
        venv.EnvBuilder(with_pip=True).create(venv_dir)

    print(f"Installing dependencies ({', '.join(DEPS)}) ...")
    cmd = [str(py), "-m", "pip", "install", "--quiet", "--upgrade", *DEPS]
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        print("ERROR: pip install failed.", file=sys.stderr)
        print("If behind a corporate proxy/mirror, configure pip, e.g.:",
              file=sys.stderr)
        print(f"  {py} -m pip install --index-url <internal-mirror-url> "
              f"{' '.join(DEPS)}", file=sys.stderr)
        return 1

    print("OK. Scripts ready. Venv interpreter:")
    print(f"  {py}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
