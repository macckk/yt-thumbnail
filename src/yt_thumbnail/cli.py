# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface de linha de comando (Typer).

Comandos são adicionados fase a fase (ver PLANO.md). Lista completa: ``docs/uso-cli.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
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

    Fluxo: transcrição > Claude > SDXL > Pillow > revisão > envio.
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
    so_novos: Annotated[
        bool, typer.Option("--so-novos", help="Na tabela, mostra só os vídeos novos.")
    ] = False,
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
                        completar=_completador_playlist(cfg, canal.channel_id),
                    )
                except ErroPlaylist as e:
                    console.print(f"[red]Erro no job {j.nome}:[/] {e}")
                    falhou = True
                    continue

            tabela = Table(title=f"Job {j.nome} — {escape(j.playlist)}")
            for col in ("#", "ID", "Tipo", "Duração", "Dimensões", "Título", ""):
                tabela.add_column(col)
            novos = {m.video_id for m in r.novos}
            for m in r.novos if so_novos else r.todos:
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
            if tabela.row_count:
                console.print(tabela)
            n_short = sum(m.tipo == "short" for m in r.todos)
            console.print(
                f"{len(r.todos)} vídeo(s): {len(r.todos) - n_short} longo(s), {n_short} Short(s); "
                f"{len(r.novos)} novo(s), {len(r.existentes)} já listado(s), "
                f"{len(r.erros)} erro(s)."
            )
            for vid, msg in r.erros.items():
                console.print(f"  [red]erro[/] {vid}: {escape(msg)}")
            if r.completada_por:
                console.print(
                    f"  A playlist informa {r.total_informado} vídeos; o yt-dlp leu "
                    f"{r.lidos_ytdlp} e os outros {r.completada_por} vieram pela YouTube Data API."
                )
            if r.aviso:
                console.print(f"[yellow]Aviso:[/] {escape(r.aviso)}")
            if r.canal_divergente:
                console.print(
                    f"[yellow]Aviso:[/] {len(r.canal_divergente)} vídeo(s) não são do canal "
                    f"{j.canal} ({canal.channel_id}); o envio deles será pulado. Confira o job."
                )
            falhou = falhou or bool(r.erros)
    if falhou:
        raise typer.Exit(1)


def _completador_playlist(cfg: Config, channel_id: str | None):  # noqa: ANN202
    """IDs da playlist pela YouTube Data API (só é chamado se o yt-dlp ler a lista pela metade)."""
    if not channel_id:
        return None

    def completar(playlist_id: str) -> list[str]:
        return _api_do_canal(cfg, channel_id).ids_da_playlist(playlist_id)

    return completar


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
    ou sem_fala) e registra o status `transcrito`. Jobs com `fonte_analise: titulo` não
    transcrevem (origem desativada): a análise usa só o título e a descrição.
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
                    whisper_se_legenda_falhar=tc.whisper_se_legenda_falhar,
                    manter_audio=tc.manter_audio,
                    limite=limite,
                    ao_progredir=progresso,
                    desativada=j.fonte_analise == "titulo",
                )
            origens = Counter(r.feitos.values())
            detalhe = ", ".join(f"{n} {o}" for o, n in origens.most_common()) or "nenhum"
            console.print(
                f"[bold]{j.nome}[/]: {len(r.feitos)} transcrito(s) ({detalhe}); "
                f"{len(r.existentes)} já transcrito(s); {len(r.erros)} erro(s)."
            )
            if r.legenda_falhou:
                console.print(
                    f"  [yellow]Aviso:[/] a legenda de {len(r.legenda_falhou)} vídeo(s) não pôde "
                    "ser baixada e foi usado o Whisper (ex.: "
                    f"{escape(next(iter(r.legenda_falhou.values())))})."
                )
            for vid, msg in r.erros.items():
                console.print(f"  [red]erro[/] {vid}: {escape(msg)}")
            if r.erros or r.legenda_falhou:
                console.print(f"  Dicas: {DOCS_PROBLEMAS}#transcrição")
            falhou = falhou or bool(r.erros)
    if falhou:
        raise typer.Exit(1)


@app.command()
def analisar(
    job: OpcaoJob = None,
    ids: OpcaoIds = None,
    tipo: OpcaoTipo = None,
    forcar: OpcaoForcar = False,
    limite: OpcaoLimite = None,
    config: OpcaoConfig = None,
) -> None:
    """Analisa os vídeos transcritos e gera o título da capa e o prompt de imagem.

    Usa o backend de `analise.backend` (padrão: Claude Code, `claude -p`) e o tom do preset
    do job. Grava analise.json e registra o status `analisado`.
    """
    from rich.markup import escape
    from rich.table import Table

    from yt_thumbnail.analise import ErroBackend, criar_backend
    from yt_thumbnail.analise.base import analisar_job
    from yt_thumbnail.estado import abrir_estado

    cfg = _carregar(config)
    ac = cfg.analise
    arquivo_template = cfg.pasta_prompts / ac.template
    if not arquivo_template.is_file():
        console.print(f"[red]Erro:[/] template {arquivo_template} não encontrado.")
        raise typer.Exit(1)
    template = arquivo_template.read_text(encoding="utf-8")
    presets = cfg.validar_presets()
    falhou = False
    with abrir_estado(cfg.pasta_saida) as estado:
        for j in _jobs_selecionados(cfg, job):
            tipos = _tipos_do_job(j, tipo)
            if not tipos:
                console.print(f"[yellow]{j.nome}:[/] o tipo {tipo} não está em `tipos` do job.")
                continue
            try:
                backend = criar_backend(
                    ac.backend,
                    modelo=ac.modelo,
                    timeout=ac.timeout_segundos,
                    saida_estruturada=ac.saida_estruturada,
                )
                with console.status(f"[bold]{j.nome}[/]: preparando...") as status:

                    def progresso(video_id: str, i: int, total: int, _s=status, _j=j) -> None:
                        _s.update(f"[bold]{_j.nome}[/]: analisando {i}/{total} — {video_id}")

                    r = analisar_job(
                        job=j.nome,
                        tipos=tipos,
                        pasta_saida=cfg.pasta_saida,
                        estado=estado,
                        backend=backend,
                        preset=presets[j.preset],
                        template=template,
                        limite_caracteres=ac.max_caracteres_transcricao,
                        tentativas_extras=ac.tentativas,
                        ids=_ids(ids),
                        forcar=forcar,
                        limite=limite,
                        ao_progredir=progresso,
                    )
            except ErroBackend as e:
                console.print(f"[red]Erro no backend de análise:[/] {escape(str(e))}")
                raise typer.Exit(1) from e
            if r.feitos:
                tabela = Table(title=f"Job {j.nome} — análises novas")
                for col in ("ID", "Título da capa", "Emoção", "Posição", "Prompt de imagem"):
                    tabela.add_column(col)
                for vid, a in r.feitos.items():
                    tabela.add_row(
                        vid,
                        escape(a.titulo_capa),
                        escape(a.emocao),
                        a.posicao_texto,
                        escape(a.prompt_imagem[:70] + ("…" if len(a.prompt_imagem) > 70 else "")),
                    )
                console.print(tabela)
            console.print(
                f"[bold]{j.nome}[/]: {len(r.feitos)} analisado(s); "
                f"{len(r.existentes)} já analisado(s); {len(r.erros)} erro(s)."
            )
            for vid, msg in r.erros.items():
                console.print(f"  [red]erro[/] {vid}: {escape(msg)}")
            falhou = falhou or bool(r.erros)
    if falhou:
        raise typer.Exit(1)


@app.command()
def gerar(
    job: OpcaoJob = None,
    ids: OpcaoIds = None,
    tipo: OpcaoTipo = None,
    variacoes: Annotated[
        int | None,
        typer.Option("--variacoes", min=1, max=10, help="Variações por vídeo (padrão: config)."),
    ] = None,
    forcar: OpcaoForcar = False,
    limite: OpcaoLimite = None,
    config: OpcaoConfig = None,
) -> None:
    """Gera as imagens de fundo (sem texto) com SDXL na GPU de imagem.

    Usa o prompt_imagem da análise + estilo e prompt negativo do preset. Grava base_N.png e
    imagens.json (seeds) e registra o status `imagens_geradas`.
    """
    from rich.markup import escape

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.imagem import GeradorSDXL, gerar_job

    cfg = _carregar(config)
    ic = cfg.imagem
    n = variacoes or ic.variacoes
    presets = cfg.validar_presets()
    gerador = GeradorSDXL(
        ic.modelo,
        cfg.gpu.imagem,
        gpu_texto=cfg.gpu.codificadores_sdxl,
        attention_slicing=ic.attention_slicing,
        cpu_offload=ic.cpu_offload,
    )
    formatos = {
        "longo": (cfg.formatos.longo.geracao, cfg.formatos.longo.saida),
        "short": (cfg.formatos.short.geracao, cfg.formatos.short.saida),
    }
    falhou = False
    with abrir_estado(cfg.pasta_saida) as estado:
        for j in _jobs_selecionados(cfg, job):
            tipos = _tipos_do_job(j, tipo)
            if not tipos:
                console.print(f"[yellow]{j.nome}:[/] o tipo {tipo} não está em `tipos` do job.")
                continue
            with console.status(f"[bold]{j.nome}[/]: preparando...") as status:

                def progresso(video_id: str, i: int, total: int, _s=status, _j=j) -> None:
                    _s.update(
                        f"[bold]{_j.nome}[/]: gerando {i}/{total} — {video_id} "
                        "(a 1ª vez carrega o SDXL, ~1 min)"
                    )

                r = gerar_job(
                    job=j.nome,
                    tipos=tipos,
                    pasta_saida=cfg.pasta_saida,
                    estado=estado,
                    gerador=gerador,
                    preset=presets[j.preset],
                    formatos=formatos,
                    variacoes=n,
                    ids=_ids(ids),
                    forcar=forcar,
                    limite=limite,
                    ao_progredir=progresso,
                )
            tempos = [d.segundos / max(len(d.seeds), 1) for d in r.feitos.values()]
            media = f", {sum(tempos) / len(tempos):.0f} s por imagem" if tempos else ""
            console.print(
                f"[bold]{j.nome}[/]: {len(r.feitos)} vídeo(s) com imagens novas ({n} cada{media}); "
                f"{len(r.existentes)} já gerado(s); {len(r.erros)} erro(s)."
            )
            for vid, msg in r.erros.items():
                console.print(f"  [red]erro[/] {vid}: {escape(msg)}")
            falhou = falhou or bool(r.erros)
    if falhou:
        raise typer.Exit(1)


@app.command()
def compor(
    job: OpcaoJob = None,
    ids: OpcaoIds = None,
    tipo: OpcaoTipo = None,
    forcar: OpcaoForcar = False,
    limite: OpcaoLimite = None,
    config: OpcaoConfig = None,
) -> None:
    """Escreve o título sobre as imagens de fundo (Pillow) e gera as capas finais.

    Usa o titulo_capa e a posicao_texto da análise e a tipografia do preset. Grava capa_N.jpg
    (< 2 MB), a miniatura de verificação mini_N.jpg e capas.json e registra `capas_compostas`.
    """
    from rich.markup import escape

    from yt_thumbnail.composicao import ErroComposicao, abrir_fonte_do_preset, compor_job
    from yt_thumbnail.estado import abrir_estado

    cfg = _carregar(config)
    presets = cfg.validar_presets()
    falhou = False
    with abrir_estado(cfg.pasta_saida) as estado:
        for j in _jobs_selecionados(cfg, job):
            tipos = _tipos_do_job(j, tipo)
            if not tipos:
                console.print(f"[yellow]{j.nome}:[/] o tipo {tipo} não está em `tipos` do job.")
                continue
            preset = presets[j.preset]
            try:
                abrir, nome_fonte = abrir_fonte_do_preset(preset.tipografia, cfg.base)
            except ErroComposicao as e:
                console.print(f"[red]Erro:[/] {escape(str(e))}")
                raise typer.Exit(1) from e
            with console.status(f"[bold]{j.nome}[/]: preparando...") as status:

                def progresso(video_id: str, i: int, total: int, _s=status, _j=j) -> None:
                    _s.update(f"[bold]{_j.nome}[/]: compondo {i}/{total} — {video_id}")

                r = compor_job(
                    job=j.nome,
                    tipos=tipos,
                    pasta_saida=cfg.pasta_saida,
                    estado=estado,
                    preset=preset,
                    abrir=abrir,
                    nome_fonte=nome_fonte,
                    ids=_ids(ids),
                    forcar=forcar,
                    limite=limite,
                    ao_progredir=progresso,
                )
            n_capas = sum(len(d.capas) for d in r.feitos.values())
            console.print(
                f"[bold]{j.nome}[/]: {len(r.feitos)} vídeo(s) com capas novas ({n_capas} capas); "
                f"{len(r.existentes)} já composto(s); {len(r.erros)} erro(s)."
            )
            for vid, dados in r.feitos.items():
                avisos = sorted({a for c in dados.capas for a in c.avisos})
                if avisos:
                    console.print(f"  [yellow]aviso[/] {vid}: {escape('; '.join(avisos))}")
            for vid, msg in r.erros.items():
                console.print(f"  [red]erro[/] {vid}: {escape(msg)}")
            falhou = falhou or bool(r.erros)
    if falhou:
        raise typer.Exit(1)


ArgIds = Annotated[
    list[str] | None,
    typer.Argument(help="IDs dos vídeos (separados por espaço).", show_default=False),
]


@app.command()
def revisar(
    job: OpcaoJob = None,
    tipo: OpcaoTipo = None,
    abrir: Annotated[
        bool, typer.Option("--abrir/--nao-abrir", help="Abre a página no navegador.")
    ] = True,
    offline: Annotated[
        bool, typer.Option("--offline", help="Não baixa as capas atuais do YouTube.")
    ] = False,
    historico: Annotated[
        bool,
        typer.Option(
            "--historico", help="Inclui os já aprovados, rejeitados e enviados na página."
        ),
    ] = False,
    servir: Annotated[
        bool,
        typer.Option(
            "--servir",
            help="Abre a página por um servidor local com botões de aprovar/rejeitar "
            "(Ctrl+C encerra).",
        ),
    ] = False,
    porta: Annotated[
        int, typer.Option("--porta", min=0, max=65535, help="Porta do --servir.")
    ] = 8765,
    config: OpcaoConfig = None,
) -> None:
    """Gera a página de revisão (saida/<job>/revisao.html) e baixa a capa atual (backup).

    A página mostra só os vídeos aguardando decisão; `aprovar` e `rejeitar` a atualizam
    sozinhos. Com --servir, a página ganha botões que aprovam e rejeitam com um clique
    (servidor só em 127.0.0.1). A capa atual de cada vídeo vai para capa_original.jpg uma
    única vez: ela é o backup que `restaurar` usa e nunca é sobrescrita.
    """
    import webbrowser

    from rich.markup import escape

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.revisao import preparar_revisao

    cfg = _carregar(config)
    paginas = []
    selecionados = _jobs_selecionados(cfg, job)
    with abrir_estado(cfg.pasta_saida) as estado:
        for j in selecionados:
            tipos = _tipos_do_job(j, tipo)
            with console.status(f"[bold]{j.nome}[/]: baixando capas atuais e montando a página..."):
                r = preparar_revisao(
                    job=j.nome,
                    pasta_saida=cfg.pasta_saida,
                    estado=estado,
                    tipos=tipos,
                    baixar=None if offline else _baixador_padrao(),
                    incluir_decididos=historico,
                )
            pend = sum(1 for i in r.itens if i.registro.status == "capas_compostas")
            console.print(
                f"[bold]{j.nome}[/]: {len(r.itens)} vídeo(s) na revisão, {pend} pendente(s); "
                f"{len(r.originais_baixadas)} capa(s) atual(is) baixada(s) agora."
            )
            for vid, msg in r.avisos.items():
                console.print(f"  [yellow]aviso[/] {vid}: {escape(msg)}")
            if r.pagina is not None:
                console.print(f"  página: {r.pagina.resolve()}")
                paginas.append(r.pagina)
    if servir:
        _servir_revisao(cfg, {j.nome: _tipos_do_job(j, tipo) for j in selecionados}, porta, abrir)
        return
    if abrir:
        for p in paginas:
            webbrowser.open(p.resolve().as_uri())


def _servir_revisao(
    cfg: Config, tipos_por_job: dict[str, list[str]], porta: int, abrir: bool
) -> None:
    import webbrowser

    from rich.markup import escape

    from yt_thumbnail.servidor import ServidorRevisao

    try:
        servidor = ServidorRevisao(
            cfg.pasta_saida,
            tipos_por_job,
            porta,
            ao_decidir=lambda msg: console.print(f"  {escape(msg)}"),
        )
    except OSError as e:
        console.print(
            f"[red]Erro:[/] não foi possível usar a porta {porta} ({e}). "
            "Outra revisão já está aberta? Feche-a ou use --porta."
        )
        raise typer.Exit(1) from e
    with servidor:
        console.print(
            f"\n[bold]Revisão aberta em {servidor.url()}[/] — aprove e rejeite pelos botões "
            "da página.\nDeixe esta janela aberta enquanto revisa; [bold]Ctrl+C[/] encerra."
        )
        if abrir:
            for nome in tipos_por_job:
                webbrowser.open(servidor.url(nome))
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            console.print("Revisão encerrada. Próximo passo: `enviar --aprovados --dry-run`.")


def _atualizar_paginas(cfg: Config, estado, jobs: Iterable[str]) -> None:  # noqa: ANN001
    """Regrava a página de revisão dos jobs (sem rede), tirando os vídeos já decididos."""
    from yt_thumbnail.revisao import preparar_revisao

    por_nome = {j.nome: j for j in cfg.jobs}
    for nome in sorted(set(jobs)):
        j = por_nome[nome]
        r = preparar_revisao(
            job=nome,
            pasta_saida=cfg.pasta_saida,
            estado=estado,
            tipos=_tipos_do_job(j, None),
            baixar=None,
        )
        restantes = len(r.itens)
        console.print(
            f"Página de revisão de {nome} atualizada: "
            + (f"{restantes} vídeo(s) aguardando." if restantes else "nenhum vídeo aguardando.")
        )


def _baixador_padrao():  # noqa: ANN202 - isolado para os testes trocarem
    from yt_thumbnail.revisao import baixar_http

    return baixar_http


def _resolver_job(cfg: Config, estado, job: str | None, video_id: str) -> str:  # noqa: ANN001
    from yt_thumbnail.revisao import localizar_jobs

    nomes = [j.nome for j in _jobs_selecionados(cfg, job)]
    achados = localizar_jobs(estado, nomes, video_id)
    if not achados:
        raise typer.BadParameter(f"{video_id} não está em nenhum job ({', '.join(nomes)}).")
    if len(achados) > 1:
        raise typer.BadParameter(
            f"{video_id} está em mais de um job ({', '.join(achados)}); use --job."
        )
    return achados[0]


@app.command()
def aprovar(
    ids: ArgIds = None,
    variacao: Annotated[
        int, typer.Option("--variacao", "-v", min=1, help="Número da variação (1, 2, 3...).")
    ] = ...,  # type: ignore[assignment]
    todos: Annotated[
        bool, typer.Option("--todos", help="Todos os vídeos pendentes de revisão.")
    ] = False,
    job: OpcaoJob = None,
    tipo: OpcaoTipo = None,
    forcar: Annotated[
        bool, typer.Option("--forcar", help="Permite mudar a decisão de vídeo já enviado.")
    ] = False,
    config: OpcaoConfig = None,
) -> None:
    """Aprova uma variação de capa: `aprovar ID --variacao 2` ou `aprovar --todos --variacao 1`."""
    from rich.markup import escape

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.revisao import ErroRevisao, pendentes
    from yt_thumbnail.revisao import aprovar as aprovar_video

    if bool(ids) == todos:
        raise typer.BadParameter("informe os IDs ou --todos (um dos dois).")
    cfg = _carregar(config)
    falhou = False
    with abrir_estado(cfg.pasta_saida) as estado:
        if todos:
            alvos = [
                (j.nome, vid)
                for j in _jobs_selecionados(cfg, job)
                for vid in pendentes(estado, j.nome, _tipos_do_job(j, tipo))
            ]
        else:
            alvos = [(_resolver_job(cfg, estado, job, vid), vid) for vid in ids or []]
        for nome_job, vid in alvos:
            try:
                aprovar_video(estado, cfg.pasta_saida, nome_job, vid, variacao, forcar=forcar)
            except ErroRevisao as e:
                console.print(f"[red]erro[/] {escape(str(e))}")
                falhou = True
            else:
                console.print(f"[green]aprovado[/] {nome_job}/{vid}: variação {variacao}")
        _atualizar_paginas(cfg, estado, (n for n, _ in alvos))
    if not alvos:
        console.print("Nenhum vídeo pendente de revisão.")
    if falhou:
        raise typer.Exit(1)


@app.command()
def rejeitar(
    ids: Annotated[list[str], typer.Argument(help="IDs dos vídeos.", show_default=False)],
    job: OpcaoJob = None,
    forcar: Annotated[
        bool, typer.Option("--forcar", help="Permite mudar a decisão de vídeo já enviado.")
    ] = False,
    config: OpcaoConfig = None,
) -> None:
    """Rejeita as capas de um vídeo (ele não será enviado)."""
    from rich.markup import escape

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.revisao import ErroRevisao
    from yt_thumbnail.revisao import rejeitar as rejeitar_video

    cfg = _carregar(config)
    falhou = False
    with abrir_estado(cfg.pasta_saida) as estado:
        feitos = []
        for vid in ids:
            nome_job = _resolver_job(cfg, estado, job, vid)
            try:
                rejeitar_video(estado, nome_job, vid, forcar=forcar)
            except ErroRevisao as e:
                console.print(f"[red]erro[/] {escape(str(e))}")
                falhou = True
            else:
                console.print(f"[yellow]rejeitado[/] {nome_job}/{vid}")
                feitos.append(nome_job)
        _atualizar_paginas(cfg, estado, feitos)
    if falhou:
        raise typer.Exit(1)


def _api_do_canal(cfg: Config, channel_id: str):  # noqa: ANN202 - isolado para os testes
    from yt_thumbnail.youtube_api import ApiYouTube, carregar_credenciais, servico

    return ApiYouTube(servico(carregar_credenciais(cfg.pasta_secrets, channel_id)))


def _autenticar(cfg: Config, abrir_navegador: bool):  # noqa: ANN202 - isolado para os testes
    from yt_thumbnail.youtube_api import autenticar_navegador, canal_do_token, servico

    credenciais = autenticar_navegador(cfg.pasta_secrets, abrir_navegador)
    return credenciais, canal_do_token(servico(credenciais))


@app.command()
def auth(
    canal: Annotated[str, typer.Option("--canal", help="Apelido do canal (seção `canais`).")],
    abrir: Annotated[
        bool,
        typer.Option("--abrir/--nao-abrir", help="Abre o navegador (senão, mostra o endereço)."),
    ] = True,
    config: OpcaoConfig = None,
) -> None:
    """Faz o login no YouTube de um canal (OAuth) e guarda o token em secrets/tokens/.

    Rode no computador que tem navegador: abre a página do Google, você escolhe a conta e o
    canal e autoriza. Se o channel_id do canal estiver vazio no config.yaml, ele é preenchido.
    """
    from rich.markup import escape

    from yt_thumbnail.config import caminho_config
    from yt_thumbnail.youtube_api import ErroYouTube, gravar_channel_id_no_config, gravar_token

    cfg = _carregar(config)
    if canal not in cfg.canais:
        raise typer.BadParameter(f"canal {canal!r} não está em `canais` do config.yaml.")
    esperado = cfg.canais[canal].channel_id
    console.print(f"Abrindo o login do Google para o canal [bold]{canal}[/]...")
    try:
        credenciais, obtido = _autenticar(cfg, abrir)
    except ErroYouTube as e:
        console.print(f"[red]Erro:[/] {escape(str(e))}")
        raise typer.Exit(1) from e
    if esperado and obtido.channel_id != esperado:
        console.print(
            f"[red]Erro:[/] você autorizou o canal [bold]{escape(obtido.titulo)}[/] "
            f"({obtido.channel_id}), mas `{canal}` no config.yaml é {esperado}. Rode de novo e "
            "escolha o canal certo (contas com vários canais pedem a escolha no login)."
        )
        raise typer.Exit(1)
    destino = gravar_token(cfg.pasta_secrets, obtido.channel_id, credenciais)
    console.print(
        f"[green]OK[/] canal [bold]{escape(obtido.titulo)}[/] ({obtido.channel_id}); "
        f"token em {destino}"
    )
    if not esperado:
        arquivo = caminho_config(config)
        if gravar_channel_id_no_config(arquivo, canal, obtido.channel_id):
            console.print(f"channel_id de `{canal}` gravado em {arquivo}.")
        else:
            console.print(
                f"[yellow]Preencha à mão[/] em {arquivo}: canais > {canal} > "
                f"channel_id: {obtido.channel_id}"
            )


@app.command()
def canais(config: OpcaoConfig = None) -> None:
    """Lista os canais do config.yaml e confere o login (token) de cada um."""
    from rich.markup import escape
    from rich.table import Table

    from yt_thumbnail.youtube_api import ErroYouTube, caminho_token, canal_do_token

    cfg = _carregar(config)
    tabela = Table("Apelido", "channel_id", "Login", "Canal no YouTube", "Shorts", "Jobs")
    falhou = False
    for apelido, c in cfg.canais.items():
        jobs = ", ".join(j.nome for j in cfg.jobs if j.canal == apelido) or "—"
        shorts = "capa própria" if c.shorts_capa_personalizada else "não elegível"
        if not c.channel_id:
            tabela.add_row(apelido, "—", "[yellow]falta `auth`[/]", "—", shorts, jobs)
            falhou = True
            continue
        if not caminho_token(cfg.pasta_secrets, c.channel_id).is_file():
            tabela.add_row(apelido, c.channel_id, "[yellow]falta `auth`[/]", "—", shorts, jobs)
            falhou = True
            continue
        try:
            api = _api_do_canal(cfg, c.channel_id)
            titulo = canal_do_token(api.api).titulo
        except ErroYouTube as e:
            tabela.add_row(apelido, c.channel_id, f"[red]{escape(str(e))}[/]", "—", shorts, jobs)
            falhou = True
            continue
        tabela.add_row(apelido, c.channel_id, "[green]OK[/]", escape(titulo), shorts, jobs)
    console.print(tabela)
    if falhou:
        raise typer.Exit(1)


@app.command()
def enviar(
    aprovados: Annotated[
        bool, typer.Option("--aprovados", help="Obrigatório: envia as capas aprovadas.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Só mostra o que seria enviado.")
    ] = False,
    job: OpcaoJob = None,
    ids: OpcaoIds = None,
    tipo: OpcaoTipo = None,
    limite: OpcaoLimite = None,
    config: OpcaoConfig = None,
) -> None:
    """Envia ao YouTube as capas aprovadas (thumbnails.set). Use --dry-run antes.

    Confere o canal de cada vídeo, exige o backup da capa atual (`revisar`) e pula Shorts de
    canais sem capa personalizada (`nao_elegivel`).
    """
    from rich.markup import escape

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.youtube_api import ErroYouTube, enviar_job

    if not aprovados:
        raise typer.BadParameter("use `enviar --aprovados` (e `--dry-run` para simular).")
    cfg = _carregar(config)
    falhou = False
    with abrir_estado(cfg.pasta_saida) as estado:
        for j in _jobs_selecionados(cfg, job):
            canal = cfg.canais[j.canal]
            tipos = _tipos_do_job(j, tipo)
            try:
                api = (
                    None
                    if dry_run or not canal.channel_id
                    else _api_do_canal(cfg, canal.channel_id)
                )
                with console.status(f"[bold]{j.nome}[/]: enviando...") as status:

                    def progresso(video_id: str, i: int, total: int, _s=status, _j=j) -> None:
                        _s.update(f"[bold]{_j.nome}[/]: {i}/{total} — {video_id}")

                    r = enviar_job(
                        job=j.nome,
                        tipos=tipos,
                        pasta_saida=cfg.pasta_saida,
                        estado=estado,
                        channel_id=canal.channel_id,
                        shorts_capa_personalizada=canal.shorts_capa_personalizada,
                        api=api,
                        dry_run=dry_run,
                        ids=_ids(ids),
                        limite=limite,
                        pausa=cfg.envio.pausa_segundos,
                        ao_progredir=progresso,
                    )
            except ErroYouTube as e:
                console.print(f"[red]{j.nome}:[/] {escape(str(e))}")
                falhou = True
                continue
            if dry_run:
                console.print(
                    f"[bold]{j.nome}[/] (simulação): {len(r.simulados)} seriam enviados; "
                    f"{len(r.nao_elegiveis)} não elegível(is); {len(r.pulados)} pulado(s); "
                    f"{len(r.erros)} erro(s)."
                )
                for vid in r.simulados:
                    variacao = estado.obter(j.nome, vid).dados.get("variacao")  # type: ignore[union-attr]
                    console.print(f"  enviaria {vid}: variação {variacao}")
            else:
                console.print(
                    f"[bold]{j.nome}[/]: {len(r.enviados)} enviado(s); "
                    f"{len(r.nao_elegiveis)} não elegível(is); {len(r.pulados)} pulado(s); "
                    f"{len(r.erros)} erro(s)."
                )
            for vid, msg in r.nao_elegiveis.items():
                console.print(f"  [dim]não elegível[/] {vid}: {escape(msg)}")
            for vid, msg in r.pulados.items():
                console.print(f"  [yellow]pulado[/] {vid}: {escape(msg)}")
            for vid, msg in r.erros.items():
                console.print(f"  [red]erro[/] {vid}: {escape(msg)}")
            if r.parado_por:
                console.print(f"  [red]parado:[/] {escape(r.parado_por)}")
            falhou = falhou or bool(r.erros) or bool(r.parado_por)
    if falhou:
        raise typer.Exit(1)


@app.command()
def restaurar(
    ids: Annotated[list[str], typer.Argument(help="IDs dos vídeos.", show_default=False)],
    job: OpcaoJob = None,
    config: OpcaoConfig = None,
) -> None:
    """Volta a capa original do vídeo (capa_original.jpg, o backup feito por `revisar`)."""
    from rich.markup import escape

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.youtube_api import ErroYouTube, restaurar_video

    cfg = _carregar(config)
    falhou = False
    with abrir_estado(cfg.pasta_saida) as estado:
        for vid in ids:
            nome_job = _resolver_job(cfg, estado, job, vid)
            canal = cfg.canais[cfg.job(nome_job).canal]
            try:
                if not canal.channel_id:
                    raise ErroYouTube("canal sem channel_id; rode `yt-thumbnail auth`")
                restaurar_video(
                    api=_api_do_canal(cfg, canal.channel_id),
                    estado=estado,
                    pasta_saida=cfg.pasta_saida,
                    job=nome_job,
                    video_id=vid,
                    channel_id=canal.channel_id,
                )
            except ErroYouTube as e:
                console.print(f"[red]erro[/] {escape(str(e))}")
                falhou = True
            except Exception as e:  # noqa: BLE001 - erro da API
                console.print(f"[red]erro[/] {vid}: {escape(str(e))}")
                falhou = True
            else:
                console.print(f"[green]restaurada[/] a capa original de {nome_job}/{vid}")
    if falhou:
        raise typer.Exit(1)


@app.command()
def tudo(
    job: OpcaoJob = None,
    tipo: OpcaoTipo = None,
    limite: OpcaoLimite = None,
    ate: Annotated[
        str,
        typer.Option(
            "--ate",
            help="Última etapa: listar, transcrever, analisar, gerar, compor ou revisar.",
        ),
    ] = "revisar",
    abrir: Annotated[
        bool, typer.Option("--abrir/--nao-abrir", help="Abre a página de revisão no fim.")
    ] = False,
    config: OpcaoConfig = None,
) -> None:
    """Roda listar, transcrever, analisar, gerar, compor e revisar, e para na revisão.

    Cada etapa só processa o que falta: rodar de novo continua de onde parou. Erros de um
    vídeo não param o fluxo (ficam no estado e no resumo). O envio é sempre explícito
    (`enviar --aprovados`). Log em saida/logs/tudo-AAAAMMDD-HHMMSS.log.
    """
    import time

    from rich.markup import escape
    from rich.table import Table

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.orquestracao import (
        ETAPAS,
        ResultadoEtapa,
        arquivo_log,
        liberar_memoria,
        resumir,
    )

    if ate not in ETAPAS:
        raise typer.BadParameter(f"--ate deve ser uma de: {', '.join(ETAPAS)}")
    cfg = _carregar(config)
    jobs = _jobs_selecionados(cfg, job)
    for j in jobs:
        _tipos_do_job(j, tipo)  # valida --tipo antes de começar
    etapas = ETAPAS[: ETAPAS.index(ate) + 1]
    comuns = {"job": job, "config": config}
    chamadas = {
        "listar": lambda: listar(**comuns, ids=None, forcar=False, so_novos=True),
        "transcrever": lambda: transcrever(
            **comuns, ids=None, tipo=tipo, forcar=False, forcar_whisper=False, limite=limite
        ),
        "analisar": lambda: analisar(**comuns, ids=None, tipo=tipo, forcar=False, limite=limite),
        "gerar": lambda: gerar(
            **comuns, ids=None, tipo=tipo, variacoes=None, forcar=False, limite=limite
        ),
        "compor": lambda: compor(**comuns, ids=None, tipo=tipo, forcar=False, limite=limite),
        "revisar": lambda: revisar(
            **comuns, tipo=tipo, abrir=abrir, offline=False, historico=False
        ),
    }

    gravando = console.record
    console.record = True
    inicio_geral = time.perf_counter()
    console.rule(f"yt-thumbnail tudo — {', '.join(j.nome for j in jobs)}")
    resultados: list[ResultadoEtapa] = []
    try:
        for nome in etapas:
            console.rule(f"[bold]{nome}[/]")
            t0 = time.perf_counter()
            try:
                chamadas[nome]()
            except typer.Exit as e:
                codigo = getattr(e, "exit_code", 1)
                resultados.append(
                    ResultadoEtapa(nome, False, time.perf_counter() - t0, "com erros")
                )
                if codigo not in (0, 1):  # erro de configuração/uso: não adianta seguir
                    raise
            except Exception as e:  # noqa: BLE001 - uma etapa quebrada não perde o log
                console.print(f"[red]Falha inesperada em {nome}:[/] {escape(repr(e))}")
                resultados.append(ResultadoEtapa(nome, False, time.perf_counter() - t0, repr(e)))
            else:
                resultados.append(ResultadoEtapa(nome, True, time.perf_counter() - t0))
            finally:
                liberar_memoria()

        console.rule("[bold]resumo[/]")
        etapas_tab = Table("Etapa", "Resultado", "Tempo")
        for r in resultados:
            situacao = "[green]OK[/]" if r.ok else f"[yellow]{escape(r.detalhe)}[/]"
            etapas_tab.add_row(r.nome, situacao, _duracao(r.segundos))
        console.print(etapas_tab)

        houve_erro = False
        with abrir_estado(cfg.pasta_saida) as estado:
            jobs_tab = Table(
                "Job",
                "Vídeos",
                "Na revisão",
                "Pendentes",
                "Aprovados",
                "Enviados",
                "Não elegíveis",
                "Com erro",
            )
            resumos = []
            for j in jobs:
                tipos = set(_tipos_do_job(j, tipo))
                rs = resumir(estado, j.nome, tipos)
                resumos.append(rs)
                jobs_tab.add_row(
                    j.nome,
                    str(rs.total),
                    str(rs.chegaram_a_revisao),
                    str(rs.pendentes_revisao),
                    str(rs.aprovados),
                    str(rs.por_status["enviado"]),
                    str(len(rs.nao_elegiveis)),
                    str(len(rs.erros)),
                )
            console.print(jobs_tab)
            for rs in resumos:
                for vid, (etapa, msg) in sorted(rs.erros.items()):
                    houve_erro = True
                    console.print(f"  [red]erro[/] {rs.job}/{vid} ({etapa}): {escape(msg)}")
        pendentes = sum(r.pendentes_revisao for r in resumos)
        console.print(
            f"Tempo total: {_duracao(time.perf_counter() - inicio_geral)}. "
            + (
                f"{pendentes} vídeo(s) aguardando revisão: rode `revisar --servir` e aprove "
                "pelos botões da página; depois `enviar --aprovados --dry-run`."
                if pendentes
                else "Nenhum vídeo aguardando revisão."
            )
        )
    finally:
        log = arquivo_log(cfg.pasta_saida)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(console.export_text(clear=True), encoding="utf-8")
        console.record = gravando
        console.print(f"Log: {log}")
    if houve_erro or not all(r.ok for r in resultados):
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    app()
