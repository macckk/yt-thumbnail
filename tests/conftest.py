# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures compartilhadas."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def raiz() -> Path:
    """Raiz do repositório."""
    return RAIZ


@pytest.fixture
def projeto(tmp_path: Path) -> Path:
    """Pasta temporária com config.yaml (cópia do exemplo) e presets/."""
    shutil.copytree(RAIZ / "presets", tmp_path / "presets")
    shutil.copy(RAIZ / "config.example.yaml", tmp_path / "config.yaml")
    return tmp_path
