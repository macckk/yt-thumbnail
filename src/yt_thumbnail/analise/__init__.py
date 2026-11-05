# SPDX-License-Identifier: GPL-3.0-or-later
"""Fase 3 — análise do conteúdo e geração do prompt de imagem e do título da capa.

Backends disponíveis: ``claude_code`` (padrão). Para criar outro (API da Anthropic, Ollama...),
implemente :class:`~yt_thumbnail.analise.base.BackendAnalise` e registre em :func:`criar_backend`.
"""

from __future__ import annotations

from yt_thumbnail.analise.base import BackendAnalise, ErroAnalise, ErroBackend


def criar_backend(
    nome: str,
    *,
    modelo: str | None = None,
    timeout: float = 300,
    saida_estruturada: bool = True,
) -> BackendAnalise:
    """Instancia o backend de análise pelo nome configurado em ``analise.backend``.

    Raises:
        ErroBackend: se o nome não for conhecido.
    """
    if nome == "claude_code":
        from yt_thumbnail.analise.claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend(
            modelo=modelo, timeout=timeout, saida_estruturada=saida_estruturada
        )
    raise ErroBackend(f"backend de análise desconhecido: {nome!r} (disponível: claude_code)")


__all__ = ["BackendAnalise", "ErroAnalise", "ErroBackend", "criar_backend"]
