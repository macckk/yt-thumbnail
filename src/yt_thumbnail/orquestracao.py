# SPDX-License-Identifier: GPL-3.0-or-later
"""Fase 8 — orquestração: roda as etapas em sequência até a revisão e resume o estado.

O comando ``yt-thumbnail tudo`` chama, nesta ordem, ``listar → transcrever → analisar →
gerar → compor → revisar`` e **para na revisão**: o envio é sempre explícito. Cada etapa só
processa o que falta, então reexecutar continua de onde parou.

As etapas rodam uma depois da outra (sem workers em paralelo): no PC das GPUs, com 8 GB de RAM,
Whisper (~3 GB) e SDXL (~5–7 GB) carregados ao mesmo tempo estouram a memória. Entre as etapas
os modelos são liberados (:func:`liberar_memoria`).
"""

from __future__ import annotations

import gc
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from yt_thumbnail.estado import ORDEM, Estado

ETAPAS = ("listar", "transcrever", "analisar", "gerar", "compor", "revisar")


def liberar_memoria() -> None:
    """Coleta o lixo e devolve à GPU a memória em cache do PyTorch (se ele foi carregado)."""
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():  # pragma: no cover - precisa de GPU
        torch.cuda.empty_cache()


def arquivo_log(pasta_saida: Path, agora: datetime | None = None) -> Path:
    """``<saida>/logs/tudo-AAAAMMDD-HHMMSS.log``."""
    agora = agora or datetime.now()
    return pasta_saida / "logs" / f"tudo-{agora:%Y%m%d-%H%M%S}.log"


@dataclass
class ResultadoEtapa:
    """Como uma etapa terminou."""

    nome: str
    ok: bool
    segundos: float
    detalhe: str = ""


@dataclass
class ResumoJob:
    """Situação de um job no estado."""

    job: str
    total: int = 0
    por_status: Counter[str] = field(default_factory=Counter)
    erros: dict[str, tuple[str, str]] = field(default_factory=dict)  # id -> (etapa, mensagem)
    nao_elegiveis: list[str] = field(default_factory=list)

    @property
    def pendentes_revisao(self) -> int:
        return self.por_status["capas_compostas"]

    @property
    def aprovados(self) -> int:
        return self.por_status["aprovado"]

    @property
    def chegaram_a_revisao(self) -> int:
        return sum(n for s, n in self.por_status.items() if ORDEM[s] >= ORDEM["capas_compostas"])


def resumir(estado: Estado, job: str, tipos: set[str] | None = None) -> ResumoJob:
    """Conta os vídeos do job por status e junta os erros pendentes."""
    resumo = ResumoJob(job)
    for r in estado.listar(job):
        if tipos is not None and r.tipo not in tipos:
            continue
        resumo.total += 1
        resumo.por_status[r.status] += 1
        if r.erro:
            resumo.erros[r.video_id] = (r.erro, (r.mensagem or "").splitlines()[0][:160])
        if r.status == "nao_elegivel":
            resumo.nao_elegiveis.append(r.video_id)
    return resumo
