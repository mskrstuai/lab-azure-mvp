"""Terraform validator — write modules to disk, run `terraform fmt/init/validate`.

Optional LLM auto-fix loop on validation failure (max 1 attempt to keep cost
predictable).  If terraform binary isn't installed, validation is skipped and
``validation_passed`` stays False with an informative log message.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .schema import TerraformModule

logger = logging.getLogger(__name__)


def _has_terraform() -> bool:
    return shutil.which("terraform") is not None


def _run(cmd: List[str], cwd: Path, timeout: float = 60.0) -> Tuple[int, str]:
    """Run a subprocess; return (returncode, combined stdout/stderr)."""
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError as e:
        return 127, str(e)
    except subprocess.TimeoutExpired:
        return -1, f"timeout after {timeout}s"


def write_modules_to_disk(
    work_dir: Path,
    root_module: TerraformModule,
    modules: List[TerraformModule],
) -> None:
    """Materialize the root + sub-modules under ``work_dir``."""
    work_dir.mkdir(parents=True, exist_ok=True)

    # Root files at top level
    for filename, content in (root_module.files or {}).items():
        (work_dir / filename).write_text(content, encoding="utf-8")

    # Sub-modules under modules/<name>/
    modules_root = work_dir / "modules"
    modules_root.mkdir(exist_ok=True)
    for mod in modules:
        if mod.name == "root":
            continue
        mod_dir = modules_root / mod.name
        mod_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in (mod.files or {}).items():
            (mod_dir / filename).write_text(content, encoding="utf-8")


def validate_terraform(work_dir: Path) -> Dict[str, object]:
    """Run terraform fmt + init + validate.  Returns log + status."""
    log: List[str] = []

    if not _has_terraform():
        log.append("⚠ terraform 바이너리가 없어 검증을 건너뜁니다.")
        return {"passed": False, "skipped": True, "log": log, "errors": ""}

    # 1. fmt (auto-fixes formatting)
    rc, out = _run(["terraform", "fmt", "-recursive"], work_dir, timeout=30)
    log.append(f"$ terraform fmt -recursive  →  rc={rc}")
    if out.strip():
        log.append(out.strip())

    # 2. init (no backend, just providers)
    rc, out = _run(["terraform", "init", "-backend=false", "-input=false", "-no-color"], work_dir, timeout=180)
    log.append(f"$ terraform init -backend=false  →  rc={rc}")
    if out.strip():
        log.append(out.strip()[-1500:])
    if rc != 0:
        return {"passed": False, "skipped": False, "log": log, "errors": out}

    # 3. validate
    rc, out = _run(["terraform", "validate", "-no-color"], work_dir, timeout=60)
    log.append(f"$ terraform validate  →  rc={rc}")
    if out.strip():
        log.append(out.strip()[-1500:])

    return {"passed": rc == 0, "skipped": False, "log": log, "errors": out if rc != 0 else ""}
