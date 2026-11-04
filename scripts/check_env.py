# SPDX-License-Identifier: GPL-3.0-or-later
"""Verifica o ambiente (GPUs, CUDA, FFmpeg, yt-dlp, Claude Code, fontes).

Uso: ``python scripts/check_env.py`` (equivale a ``yt-thumbnail ambiente``).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from yt_thumbnail.ambiente import imprimir, verificar_tudo  # noqa: E402


def main() -> int:
    """Executa as verificações e devolve o código de saída (0 = tudo OK)."""
    return 0 if imprimir(verificar_tudo(RAIZ)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
