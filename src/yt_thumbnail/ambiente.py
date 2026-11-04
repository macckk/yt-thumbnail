# SPDX-License-Identifier: GPL-3.0-or-later
"""Verificação do ambiente: GPUs, CUDA, FFmpeg, yt-dlp, Claude Code e fontes.

Usado por ``yt-thumbnail ambiente`` e por ``scripts/check_env.py``.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from yt_thumbnail.presets import ErroPreset, carregar_preset, listar_presets

GPUS_ESPERADAS = 2


@dataclass
class Item:
    """Resultado de uma verificação."""

    nome: str
    ok: bool
    detalhe: str
    dica: str = ""
    obrigatorio: bool = True


def _rodar(cmd: list[str], timeout: float = 20) -> str | None:
    """Executa um comando e devolve a 1ª linha do stdout, ou ``None`` se falhar."""
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        r = subprocess.run(
            [exe, *cmd[1:]], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    saida = (r.stdout or r.stderr).strip().splitlines()
    return saida[0] if saida else ""


def verificar_python() -> Item:
    """Versão do Python (>= 3.11)."""
    v = sys.version_info
    return Item("Python", v >= (3, 11), f"{v.major}.{v.minor}.{v.micro}", "Instale o Python 3.11+.")


def verificar_gpus() -> list[Item]:
    """GPUs NVIDIA, VRAM e versão do CUDA (via PyTorch; senão via nvidia-smi)."""
    itens: list[Item] = []
    if importlib.util.find_spec("torch") is not None:
        import torch  # type: ignore[import-not-found]

        cuda = torch.version.cuda
        disponivel = torch.cuda.is_available()
        itens.append(
            Item(
                "PyTorch + CUDA",
                disponivel,
                f"torch {torch.__version__}, CUDA {cuda or 'ausente (build só-CPU)'}",
                "Reinstale o PyTorch com CUDA (docs/instalacao-windows.md, passo 4).",
            )
        )
        n = torch.cuda.device_count() if disponivel else 0
        for i in range(n):
            p = torch.cuda.get_device_properties(i)
            vram = p.total_memory / 1024**3
            itens.append(
                Item(
                    f"GPU {i}",
                    vram >= 7.5,
                    f"{p.name} — {vram:.1f} GB",
                    "SDXL e Whisper pedem ~8 GB.",
                )
            )
        itens.append(
            Item(
                "Quantidade de GPUs",
                n >= GPUS_ESPERADAS,
                f"{n} encontrada(s), {GPUS_ESPERADAS} esperadas",
                "Com 1 GPU, use o mesmo índice em gpu.transcricao e gpu.imagem (mais lento).",
            )
        )
        return itens

    linha = _rodar(["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader"])
    if linha is None:
        itens.append(
            Item(
                "GPU NVIDIA",
                False,
                "nvidia-smi não encontrado",
                "Instale o driver NVIDIA (docs/instalacao-windows.md, passo 1).",
            )
        )
    else:
        itens.append(Item("GPU NVIDIA (nvidia-smi)", True, linha))
    itens.append(
        Item(
            "PyTorch",
            False,
            "não instalado",
            "Instale o PyTorch com CUDA e o extra [gpu] (docs/instalacao-windows.md, passo 4).",
        )
    )
    return itens


def verificar_modulos() -> list[Item]:
    """Bibliotecas de GPU opcionais (extra ``[gpu]``)."""
    itens = []
    for mod in ("diffusers", "transformers", "accelerate", "faster_whisper"):
        ok = importlib.util.find_spec(mod) is not None
        itens.append(Item(mod, ok, "instalado" if ok else "ausente", 'pip install -e ".[gpu]"'))
    return itens


def verificar_ferramentas() -> list[Item]:
    """FFmpeg, yt-dlp e Claude Code."""
    ffmpeg = _rodar(["ffmpeg", "-version"])
    itens = [
        Item(
            "FFmpeg",
            ffmpeg is not None,
            ffmpeg or "não encontrado no PATH",
            "winget install Gyan.FFmpeg (e reabra o terminal).",
        )
    ]
    if importlib.util.find_spec("yt_dlp") is not None:
        from yt_dlp.version import __version__ as ver_ytdlp

        itens.append(Item("yt-dlp", True, ver_ytdlp))
    else:
        itens.append(Item("yt-dlp", False, "não instalado", "pip install -e ."))
    claude = _rodar(["claude", "--version"])
    itens.append(
        Item(
            "Claude Code",
            claude is not None,
            claude or "comando `claude` não encontrado",
            "Instale o Claude Code e faça login (docs/instalacao-windows.md, passo 6).",
        )
    )
    return itens


def verificar_fontes(raiz: Path) -> list[Item]:
    """Fontes referenciadas pelos presets em ``<raiz>/presets``."""
    pasta = raiz / "presets"
    itens: list[Item] = []
    for nome in listar_presets(pasta):
        try:
            preset = carregar_preset(nome, pasta)
        except ErroPreset as e:
            itens.append(Item(f"Preset {nome}", False, str(e).splitlines()[0]))
            continue
        tip = preset.tipografia
        for fonte, obrig in ((tip.fonte, True), (tip.fonte_alternativa, False)):
            if fonte is None:
                continue
            caminho = fonte if fonte.is_absolute() else raiz / fonte
            itens.append(
                Item(
                    f"Fonte ({nome})",
                    caminho.is_file(),
                    str(fonte),
                    "python scripts/baixar_fontes.py",
                    obrigatorio=obrig,
                )
            )
    if not itens:
        itens.append(Item("Presets", False, f"nenhum preset em {pasta}"))
    return itens


def verificar_tudo(raiz: Path) -> list[Item]:
    """Executa todas as verificações."""
    return [
        verificar_python(),
        *verificar_gpus(),
        *verificar_modulos(),
        *verificar_ferramentas(),
        *verificar_fontes(raiz),
    ]


def imprimir(itens: list[Item]) -> bool:
    """Mostra a tabela de resultados; devolve ``True`` se todos os obrigatórios passaram."""
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    tabela = Table(title="yt-thumbnail — verificação do ambiente")
    tabela.add_column("", width=4)
    tabela.add_column("Item")
    tabela.add_column("Detalhe")
    tabela.add_column("O que fazer")
    for it in itens:
        marca = (
            "[green]OK[/]" if it.ok else ("[red]FALHA[/]" if it.obrigatorio else "[yellow]AVISO[/]")
        )
        tabela.add_row(marca, escape(it.nome), escape(it.detalhe), "" if it.ok else escape(it.dica))
    Console().print(tabela)
    return all(it.ok for it in itens if it.obrigatorio)
