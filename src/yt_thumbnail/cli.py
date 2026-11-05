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
from yt_thumbnail.config import Config, ErroConfig, Job, carregar_config

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


def _carregar(config: Path | None) -> Config:
    try:
        return carregar_config(config)
    except ErroConfig as e:
        console.print(f"[red]Erro:[/] {e}")
        raise typer.Exit(1) from e


def _jobs_selecionados(cfg: Config, job: str | None) -> list[Job]:
    if job is None:
        if not cfg.jobs:
            console.print("[red]Erro:[/] nenhum job em `jobs` no config.yaml.")
            raise typer.Exit(1)
        return cfg.jobs
    try:
        return [cfg.job(job)]
    except ErroConfig as e:
        console.print(f"[red]Erro:[/] {e}")
        raise typer.Exit(1) from e


def _ids(ids: str | None) -> list[str] | None:
    return [i.strip() for i in ids.split(",") if i.strip()] if ids else None


def _duracao(segundos: float | None) -> str:
    if segundos is None:
        return "?"
    s = int(segundos)
    return (
        f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    )


OpcaoJob = Annotated[
    str | None, typer.Option("--job", "-j", help="Nome do job (padrão: todos os jobs).")
]
OpcaoIds = Annotated[
    str | None, typer.Option("--ids", help="Restringe a estes IDs de vídeo, separados por vírgula.")
]
OpcaoForcar = Annotated[bool, typer.Option("--forcar", help="Refaz a etapa mesmo se já existir.")]


@app.command()
def listar(
    job: OpcaoJob = None,
    ids: OpcaoIds = None,
    forcar: OpcaoForcar = False,
    config: OpcaoConfig = None,
) -> None:
    """Lista os vídeos da playlist de cada job e detecta o tipo (longo/Short).

    Grava saida/<job>/<video_id>/meta.json e registra o status `listado`. Não baixa mídia.
    """
    from rich.markup import escape
    from rich.table import Table

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.playlist import ErroPlaylist, listar_job, opcoes_ytdlp

    cfg = _carregar(config)
    falhou = False
    with abrir_estado(cfg.pasta_saida) as estado:
        for j in _jobs_selecionados(cfg, job):
            canal = cfg.canais[j.canal]
            with console.status(f"[bold]{j.nome}[/]: lendo a playlist...") as status:

                def progresso(video_id: str, i: int, total: int, _s=status, _j=j) -> None:
                    _s.update(f"[bold]{_j.nome}[/]: {i}/{total} — {video_id}")

                try:
                    r = listar_job(
                        job=j.nome,
                        url_playlist=j.playlist,
                        pasta_saida=cfg.pasta_saida,
                        estado=estado,
                        channel_id_esperado=canal.channel_id,
                        forcar=forcar,
                        ids=_ids(ids),
                        opcoes=opcoes_ytdlp(cfg.ytdlp.cookies_navegador),
                        ao_progredir=progresso,
                    )
                except ErroPlaylist as e:
                    console.print(f"[red]Erro no job {j.nome}:[/] {e}")
                    falhou = True
                    continue

            tabela = Table(title=f"Job {j.nome} — {escape(j.playlist)}")
            for col in ("#", "ID", "Tipo", "Duração", "Dimensões", "Título", ""):
                tabela.add_column(col)
            novos = {m.video_id for m in r.novos}
            for m in r.todos:
                tipo = "[magenta]SHORT[/]" if m.tipo == "short" else "[cyan]LONGO[/]"
                if m.tipo not in j.tipos:
                    tipo += " [dim](fora do job)[/]"
                dims = f"{m.largura}×{m.altura}" if m.largura and m.altura else "?"
                tabela.add_row(
                    str(m.indice_playlist or ""),
                    m.video_id,
                    tipo,
                    _duracao(m.duracao),
                    dims,
                    escape(m.titulo[:60]),
                    "[green]novo[/]" if m.video_id in novos else "",
                )
            console.print(tabela)
            n_short = sum(m.tipo == "short" for m in r.todos)
            console.print(
                f"{len(r.todos)} vídeo(s): {len(r.todos) - n_short} longo(s), {n_short} Short(s); "
                f"{len(r.novos)} novo(s), {len(r.existentes)} já listado(s), "
                f"{len(r.erros)} erro(s)."
            )
            for vid, msg in r.erros.items():
                console.print(f"  [red]erro[/] {vid}: {escape(msg)}")
            if r.canal_divergente:
                console.print(
                    f"[yellow]Aviso:[/] {len(r.canal_divergente)} vídeo(s) não são do canal "
                    f"{j.canal} ({canal.channel_id}); o envio deles será pulado. Confira o job."
                )
            falhou = falhou or bool(r.erros)
    if falhou:
        raise typer.Exit(1)


OpcaoTipo = Annotated[
    str | None,
    typer.Option("--tipo", help="Só este tipo: longo ou short (dentro dos `tipos` do job)."),
]
OpcaoLimite = Annotated[
    int | None, typer.Option("--limite", min=1, help="Processa no máximo N vídeos pendentes.")
]


def _tipos_do_job(job: Job, tipo: str | None) -> list[str]:
    if tipo is None:
        return list(job.tipos)
    if tipo not in ("longo", "short"):
        console.print("[red]Erro:[/] --tipo deve ser `longo` ou `short`.")
        raise typer.Exit(2)
    return [tipo] if tipo in job.tipos else []


@app.command()
def transcrever(
    job: OpcaoJob = None,
    ids: OpcaoIds = None,
    tipo: OpcaoTipo = None,
    forcar: OpcaoForcar = False,
    forcar_whisper: Annotated[
        bool,
        typer.Option(
            "--forcar-whisper", help="Ignora a legenda do YouTube e transcreve com o Whisper."
        ),
    ] = False,
    limite: OpcaoLimite = None,
    config: OpcaoConfig = None,
) -> None:
    """Transcreve os vídeos listados: legenda do YouTube ou, sem ela, faster-whisper na GPU.

    Grava transcricao.txt e transcricao.json (origem: legenda_manual, legenda_auto, whisper
    ou sem_fala) e registra o status `transcrito`.
    """
    from collections import Counter

    from rich.markup import escape

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.playlist import opcoes_ytdlp
    from yt_thumbnail.transcricao import TranscritorWhisper, transcrever_job

    cfg = _carregar(config)
    tc = cfg.transcricao
    transcritor = TranscritorWhisper(tc.modelo_whisper, cfg.gpu.transcricao, tc.compute_type)
    opcoes = opcoes_ytdlp(cfg.ytdlp.cookies_navegador)
    opcoes["sleep_interval_subtitles"] = tc.pausa_legendas_segundos
    falhou = False
    with abrir_estado(cfg.pasta_saida) as estado:
        for j in _jobs_selecionados(cfg, job):
            tipos = _tipos_do_job(j, tipo)
            if not tipos:
                console.print(f"[yellow]{j.nome}:[/] o tipo {tipo} não está em `tipos` do job.")
                continue
            with console.status(f"[bold]{j.nome}[/]: preparando...") as status:

                def progresso(video_id: str, i: int, total: int, _s=status, _j=j) -> None:
                    _s.update(f"[bold]{_j.nome}[/]: transcrevendo {i}/{total} — {video_id}")

                r = transcrever_job(
                    job=j.nome,
                    tipos=tipos,
                    pasta_saida=cfg.pasta_saida,
                    estado=estado,
                    transcritor=transcritor,
                    idiomas=tc.idiomas,
                    idioma_whisper=tc.idioma_whisper,
                    opcoes=opcoes,
                    ids=_ids(ids),
                    forcar=forcar,
                    forcar_whisper=forcar_whisper,
                    manter_audio=tc.manter_audio,
                    limite=limite,
                    ao_progredir=progresso,
                )
            origens = Counter(r.feitos.values())
            detalhe = ", ".join(f"{n} {o}" for o, n in origens.most_common()) or "nenhum"
            console.print(
                f"[bold]{j.nome}[/]: {len(r.feitos)} transcrito(s) ({detalhe}); "
                f"{len(r.existentes)} já transcrito(s); {len(r.erros)} erro(s)."
            )
            for vid, msg in r.erros.items():
                console.print(f"  [red]erro[/] {vid}: {escape(msg)}")
            if r.erros:
                console.print(f"  Dicas: {DOCS_PROBLEMAS}#transcrição")
            falhou = falhou or bool(r.erros)
    if falhou:
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    app()
