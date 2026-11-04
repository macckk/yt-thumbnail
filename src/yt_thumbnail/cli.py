# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface de linha de comando (Typer).

Comandos são adicionados fase a fase (ver PLANO.md). Lista completa: ``docs/uso-cli.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from yt_thumbnail import DOCS_PROBLEMAS, __version__
from yt_thumbnail.config import ErroConfig, carregar_config

app = typer.Typer(
    name="yt-thumbnail",
    help="Gerador automático de capas para playlists do YouTube.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

OpcaoConfig = Annotated[
    Path | None,
    typer.Option(
        "--config",
        "-c",
        help="Arquivo de configuração (padrão: $YT_THUMBNAIL_CONFIG ou ./config.yaml).",
        dir_okay=False,
    ),
]


def _versao(valor: bool) -> None:
    if valor:
        console.print(f"yt-thumbnail {__version__}")
        raise typer.Exit()


@app.callback()
def principal(
    versao: Annotated[
        bool,
        typer.Option(
            "--version", "-V", help="Mostra a versão e sai.", callback=_versao, is_eager=True
        ),
    ] = False,
) -> None:
    """Gera capas para playlists do YouTube.

    Fluxo: transcrição → Claude → SDXL → Pillow → revisão → envio.
    """


@app.command()
def ambiente(
    raiz: Annotated[
        Path, typer.Option(help="Raiz do projeto (onde ficam presets/ e assets/).", file_okay=False)
    ] = Path("."),
) -> None:
    """Verifica GPUs, CUDA, FFmpeg, yt-dlp, Claude Code e fontes."""
    from yt_thumbnail.ambiente import imprimir, verificar_tudo

    if not imprimir(verificar_tudo(raiz)):
        console.print(
            f"\n[red]Há itens com falha.[/] Veja a coluna 'O que fazer' e {DOCS_PROBLEMAS}"
        )
        raise typer.Exit(1)
    console.print("\n[green]Ambiente OK.[/]")


@app.command()
def validar(config: OpcaoConfig = None) -> None:
    """Valida o config.yaml e os presets usados pelos jobs."""
    try:
        cfg = carregar_config(config)
    except ErroConfig as e:
        console.print(f"[red]Erro:[/] {e}")
        raise typer.Exit(1) from e
    console.print(
        f"[green]Configuração válida:[/] {len(cfg.jobs)} job(s), {len(cfg.canais)} canal(is)."
    )
    for job in cfg.jobs:
        console.print(
            f"  • {job.nome}: canal={job.canal} preset={job.preset} tipos={','.join(job.tipos)}"
        )


if __name__ == "__main__":  # pragma: no cover
    app()
