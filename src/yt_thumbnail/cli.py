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
                    whisper_se_legenda_falhar=tc.whisper_se_legenda_falhar,
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
    config: OpcaoConfig = None,
) -> None:
    """Gera a página de revisão (saida/<job>/revisao.html) e baixa a capa atual (backup).

    A capa atual de cada vídeo vai para capa_original.jpg uma única vez: ela é o backup que
    `restaurar` usa e nunca é sobrescrita.
    """
    import webbrowser

    from rich.markup import escape

    from yt_thumbnail.estado import abrir_estado
    from yt_thumbnail.revisao import preparar_revisao

    cfg = _carregar(config)
    paginas = []
    with abrir_estado(cfg.pasta_saida) as estado:
        for j in _jobs_selecionados(cfg, job):
            tipos = _tipos_do_job(j, tipo)
            with console.status(f"[bold]{j.nome}[/]: baixando capas atuais e montando a página..."):
                r = preparar_revisao(
                    job=j.nome,
                    pasta_saida=cfg.pasta_saida,
                    estado=estado,
                    tipos=tipos,
                    baixar=None if offline else _baixador_padrao(),
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
    if abrir:
        for p in paginas:
            webbrowser.open(p.resolve().as_uri())


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
        for vid in ids:
            nome_job = _resolver_job(cfg, estado, job, vid)
            try:
                rejeitar_video(estado, nome_job, vid, forcar=forcar)
            except ErroRevisao as e:
                console.print(f"[red]erro[/] {escape(str(e))}")
                falhou = True
            else:
                console.print(f"[yellow]rejeitado[/] {nome_job}/{vid}")
    if falhou:
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    app()
