"""Versioned pre-push hook installation at the Git CLI seam."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_hook_installer_configures_the_versioned_pre_push_hook(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    shutil.copy2(ROOT / "scripts" / "install-git-hooks.sh", repo / "scripts")
    shutil.copy2(ROOT / "scripts" / "eval-local-gate.sh", repo / "scripts")
    shutil.copy2(ROOT / ".githooks" / "pre-push", repo / ".githooks")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    proc = subprocess.run(
        ["bash", "scripts/install-git-hooks.sh"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    configured = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert proc.returncode == 0
    assert configured == ".githooks"
    assert (repo / ".githooks" / "pre-push").stat().st_mode & 0o111
