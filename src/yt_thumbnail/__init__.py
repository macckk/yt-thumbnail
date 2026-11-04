# SPDX-License-Identifier: GPL-3.0-or-later
"""yt-thumbnail — gerador automático de capas para playlists do YouTube."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("yt-thumbnail")
except PackageNotFoundError:  # pragma: no cover - execução sem instalação
    __version__ = "0.0.0"

DOCS_PROBLEMAS = "https://github.com/macckk/yt-thumbnail/blob/main/docs/solucao-de-problemas.md"
