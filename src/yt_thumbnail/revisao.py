# SPDX-License-Identifier: GPL-3.0-or-later
"""Fase 6 — revisão humana: backup da capa atual, página HTML e aprovação pela CLI.

- ``capa_original.jpg``: a capa que o vídeo tem hoje no YouTube. É baixada uma única vez e
  **nunca** sobrescrita, porque também é o backup usado por ``restaurar`` (Fase 7): depois do
  envio, a capa pública passa a ser a nossa.
- ``saida/<job>/revisao.html``: página estática com, por vídeo, a capa original, as variações
  em tamanho real e em miniatura e o comando de aprovação pronto para copiar.
- :func:`aprovar` / :func:`rejeitar`: registram a escolha no estado.
"""

from __future__ import annotations

import html
import io
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from yt_thumbnail.analise.base import ler_analise
from yt_thumbnail.composicao import ArquivoCapas, ler_capas
from yt_thumbnail.estado import ORDEM, Estado, RegistroVideo
from yt_thumbnail.playlist import Meta, ler_meta, pasta_video

ORIGINAL = "capa_original.jpg"
LARGURA_MINIMA_ORIGINAL = 200
"""Imagens menores que isso são o "sem capa" cinza do YouTube (120×90), não a capa."""

Baixador = Callable[[str], bytes]


class ErroRevisao(Exception):
    """Erro de aprovação/rejeição (vídeo inexistente, variação inválida...)."""


# --------------------------------------------------------------------------- capa original


def baixar_http(url: str) -> bytes:
    """GET simples (até 10 MB)."""
    req = urllib.request.Request(url, headers={"User-Agent": "yt-thumbnail"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - URLs do i.ytimg.com
        return r.read(10 * 1024 * 1024)


def urls_capa(video_id: str, thumbnail_url: str | None) -> list[str]:
    """Candidatas à capa atual, da melhor para a pior."""
    base = f"https://i.ytimg.com/vi/{video_id}"
    urls = [thumbnail_url] if thumbnail_url else []
    urls += [f"{base}/{n}.jpg" for n in ("maxresdefault", "hq720", "sddefault", "hqdefault")]
    return list(dict.fromkeys(urls))


def baixar_original(pasta: Path, meta: Meta, baixar: Baixador = baixar_http) -> str | None:
    """Baixa a capa atual para ``capa_original.jpg`` se ainda não existir.

    Devolve a URL usada, ``None`` se o arquivo já existia. Nunca sobrescreve (é o backup).

    Raises:
        ErroRevisao: se nenhuma URL devolver uma imagem válida.
    """
    destino = pasta / ORIGINAL
    if destino.exists():
        return None
    falhas = []
    for url in urls_capa(meta.video_id, meta.thumbnail_url):
        try:
            dados = baixar(url)
            with Image.open(io.BytesIO(dados)) as img:
                img.load()
                if img.width < LARGURA_MINIMA_ORIGINAL:
                    falhas.append(f"{url}: {img.width}×{img.height}")
                    continue
                if img.format == "JPEG":
                    conteudo = dados
                else:  # webp/png -> jpg
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, "JPEG", quality=95)
                    conteudo = buf.getvalue()
        except (urllib.error.URLError, OSError, UnidentifiedImageError, ValueError) as e:
            falhas.append(f"{url}: {e}")
            continue
        temporario = destino.with_suffix(".tmp")
        temporario.write_bytes(conteudo)
        temporario.replace(destino)
        return url
    raise ErroRevisao("não foi possível baixar a capa atual (" + "; ".join(falhas[-2:]) + ")")


# --------------------------------------------------------------------------- página


@dataclass
class ItemRevisao:
    """Um vídeo na página de revisão."""

    registro: RegistroVideo
    meta: Meta
    capas: ArquivoCapas
    resumo: str
    tem_original: bool


@dataclass
class ResultadoRevisao:
    """Resumo de :func:`preparar_revisao`."""

    pagina: Path | None = None
    itens: list[ItemRevisao] = field(default_factory=list)
    originais_baixadas: list[str] = field(default_factory=list)
    avisos: dict[str, str] = field(default_factory=dict)


def _ordem_item(item: ItemRevisao) -> tuple[int, int]:
    pendente = 0 if item.registro.status == "capas_compostas" else 1
    return pendente, item.meta.indice_playlist or 0


def preparar_revisao(
    *,
    job: str,
    pasta_saida: Path,
    estado: Estado,
    tipos: Iterable[str],
    baixar: Baixador | None = baixar_http,
) -> ResultadoRevisao:
    """Baixa as capas originais que faltam e grava ``<saida>/<job>/revisao.html``.

    Entram os vídeos com capas compostas (inclusive já aprovados, rejeitados ou enviados).
    Com ``baixar=None`` não acessa a rede (a capa original aparece só se já existir).
    """
    tipos = set(tipos)
    resultado = ResultadoRevisao()
    for r in estado.listar(job):
        if r.tipo not in tipos or ORDEM[r.status] < ORDEM["capas_compostas"]:
            continue
        pasta = pasta_video(pasta_saida, job, r.video_id)
        meta, capas = ler_meta(pasta), ler_capas(pasta)
        if meta is None or capas is None:
            resultado.avisos[r.video_id] = "capas ou meta.json ausentes; rode `compor`"
            continue
        if baixar is not None:
            try:
                url = baixar_original(pasta, meta, baixar)
            except ErroRevisao as e:
                resultado.avisos[r.video_id] = str(e)
            else:
                if url is not None:
                    resultado.originais_baixadas.append(r.video_id)
                    estado.registrar(job, r.video_id, r.status, dados={"capa_original_url": url})  # type: ignore[arg-type]
        analise = ler_analise(pasta)
        resultado.itens.append(
            ItemRevisao(
                registro=estado.obter(job, r.video_id) or r,
                meta=meta,
                capas=capas,
                resumo=analise.resumo if analise else "",
                tem_original=(pasta / ORIGINAL).is_file(),
            )
        )
    resultado.itens.sort(key=_ordem_item)
    destino = pasta_saida / job / "revisao.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(montar_html(job, resultado.itens), encoding="utf-8")
    resultado.pagina = destino
    return resultado


def _e(texto: object) -> str:
    return html.escape(str(texto), quote=True)


def _situacao(r: RegistroVideo) -> tuple[str, str]:
    """(classe CSS, texto) da situação do vídeo."""
    if r.status == "aprovado":
        return "ok", f"aprovada a variação {r.dados.get('variacao', '?')}"
    if r.status == "rejeitado":
        return "nao", "rejeitado"
    if r.status == "enviado":
        return "ok", f"enviada a variação {r.dados.get('variacao', '?')}"
    if r.status == "nao_elegivel":
        return "nao", "aprovado, mas o canal não aceita capa de Short"
    return "pendente", "aguardando revisão"


def montar_html(job: str, itens: list[ItemRevisao]) -> str:
    """Página de revisão (HTML estático, imagens por caminho relativo)."""
    pendentes = sum(1 for i in itens if i.registro.status == "capas_compostas")
    cartoes = "\n".join(_cartao(job, i) for i in itens)
    gerado = datetime.now().strftime("%d/%m/%Y %H:%M")
    vazio = (
        "<p class='vazio'>Nenhum vídeo com capas compostas. Rode <code>yt-thumbnail compor</code>."
        "</p>"
        if not itens
        else ""
    )
    todos = f"yt-thumbnail aprovar --job {job} --todos --variacao 1"
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisão — {_e(job)}</title>
<style>
:root {{
  --fundo: #f6f2ea; --cartao: #fffdf8; --texto: #3b332b; --suave: #7a6e62; --borda: #e4dccd;
  --ok: #2f7d4f; --nao: #a2463b; --pendente: #9a6b12; --codigo: #f1ebe0; --destaque: #c79a3b;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --fundo: #1d1a17; --cartao: #262220; --texto: #ece5da; --suave: #a99d8f; --borda: #3a342f;
    --ok: #6fc28e; --nao: #e08a7f; --pendente: #e0b45a; --codigo: #2f2a26; --destaque: #e0b45a;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--fundo); color: var(--texto);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
header, main {{ max-width: 1400px; margin: 0 auto; padding: 16px; }}
header h1 {{ margin: 8px 0 4px; font-size: 22px; }}
header p {{ margin: 4px 0; color: var(--suave); }}
.cartao {{ background: var(--cartao); border: 1px solid var(--borda); border-radius: 12px;
  padding: 16px; margin: 0 0 20px; }}
.topo {{ display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: baseline; }}
.topo h2 {{ font-size: 17px; margin: 0; flex: 1 1 400px; }}
.topo h2 a {{ color: inherit; }}
.selo {{ font-size: 11px; font-weight: 700; letter-spacing: .08em; padding: 2px 8px;
  border-radius: 999px; background: var(--texto); color: var(--cartao); }}
.situacao {{ font-size: 13px; font-weight: 600; }}
.situacao.ok {{ color: var(--ok); }} .situacao.nao {{ color: var(--nao); }}
.situacao.pendente {{ color: var(--pendente); }}
.titulo-capa {{ font-size: 15px; margin: 6px 0 2px; }}
.resumo {{ color: var(--suave); margin: 2px 0 12px; font-size: 14px; }}
.grade {{ display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr)); }}
.short .grade {{ grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }}
figure {{ margin: 0; border: 1px solid var(--borda); border-radius: 10px; padding: 8px; }}
figure.escolhida {{ border: 2px solid var(--ok); }}
figure img.real {{ width: 100%; height: auto; display: block; border-radius: 6px; }}
figcaption {{ font-size: 13px; margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }}
.mini {{ display: flex; align-items: center; gap: 8px; color: var(--suave); font-size: 12px; }}
.mini img {{ border-radius: 4px; display: block; max-width: 100%; height: auto; }}
.cmd {{ display: flex; gap: 6px; align-items: stretch; }}
.cmd code {{ flex: 1; background: var(--codigo); border-radius: 6px; padding: 4px 6px;
  font-size: 12px; overflow-wrap: anywhere; }}
button {{ font: inherit; font-size: 12px; border: 1px solid var(--borda); background: var(--cartao);
  color: var(--texto); border-radius: 6px; padding: 2px 10px; cursor: pointer; }}
button:hover {{ border-color: var(--destaque); }}
.aviso {{ color: var(--nao); font-size: 12px; }}
.sem-original {{ display: grid; place-items: center; aspect-ratio: 16 / 9; color: var(--suave);
  background: var(--codigo); border-radius: 6px; font-size: 13px; text-align: center; }}
.short .sem-original {{ aspect-ratio: 9 / 16; }}
.rejeitar {{ margin-top: 12px; }}
.vazio {{ color: var(--suave); }}
</style>
</head>
<body>
<header>
  <h1>Revisão das capas — {_e(job)}</h1>
  <p>{len(itens)} vídeo(s), {pendentes} aguardando revisão. Página gerada em {gerado}.</p>
  <p>Escolha uma variação por vídeo e rode o comando ao lado dela (o botão copia). Para aprovar a
  variação 1 de todos os pendentes:</p>
  {_comando(todos)}
</header>
<main>
{vazio}{cartoes}
</main>
<script>
document.addEventListener("click", async (ev) => {{
  const b = ev.target.closest("button[data-cmd]");
  if (!b) return;
  try {{ await navigator.clipboard.writeText(b.dataset.cmd); b.textContent = "copiado"; }}
  catch (e) {{ b.textContent = "selecione e copie"; }}
  setTimeout(() => (b.textContent = "copiar"), 1500);
}});
</script>
</body>
</html>
"""


def _comando(cmd: str) -> str:
    return (
        f"<div class='cmd'><code>{_e(cmd)}</code>"
        f"<button type='button' data-cmd='{_e(cmd)}'>copiar</button></div>"
    )


def _cartao(job: str, item: ItemRevisao) -> str:
    r, meta, capas = item.registro, item.meta, item.capas
    vid = meta.video_id
    classe, situacao = _situacao(r)
    escolhida = r.dados.get("variacao") if r.status in ("aprovado", "enviado") else None
    larg, alt = (320, 180) if meta.tipo == "longo" else (180, 320)
    if item.tem_original:
        original = f"<img class='real' src='{_e(vid)}/{ORIGINAL}' alt='Capa atual' loading='lazy'>"
    else:
        original = "<div class='sem-original'>capa atual não baixada</div>"
    rotulo = "Capa atual (backup)" if item.tem_original else "Capa atual"
    figuras = [f"<figure>{original}<figcaption><strong>{rotulo}</strong></figcaption></figure>"]
    for n, c in enumerate(capas.capas, start=1):
        avisos = "".join(f"<span class='aviso'>⚠ {_e(a)}</span>" for a in c.avisos)
        figuras.append(
            f"<figure class='{'escolhida' if escolhida == n else ''}'>"
            f"<img class='real' src='{_e(vid)}/{_e(c.arquivo)}' alt='Variação {n}' loading='lazy'>"
            "<figcaption>"
            f"<strong>Variação {n}</strong>"
            f"<span class='mini'><img src='{_e(vid)}/{_e(c.miniatura)}' width='{larg}' "
            f"height='{alt}' alt='Variação {n} em miniatura' loading='lazy'></span>"
            f"<span class='mini'>miniatura {larg}×{alt} · fonte {c.tamanho_fonte}px · "
            f"contraste {c.contraste:.1f}:1 · {c.bytes // 1024} KB</span>"
            f"{avisos}"
            f"{_comando(f'yt-thumbnail aprovar {vid} --job {job} --variacao {n}')}"
            "</figcaption></figure>"
        )
    return f"""<section class="cartao {_e(meta.tipo)}" id="{_e(vid)}">
  <div class="topo">
    <span class="selo">{"SHORT" if meta.tipo == "short" else "LONGO"}</span>
    <h2><a href="{_e(meta.url)}" target="_blank" rel="noopener">{_e(meta.titulo)}</a></h2>
    <span class="situacao {classe}">{_e(situacao)}</span>
  </div>
  <p class="titulo-capa">Título da capa: <strong>{_e(capas.titulo)}</strong></p>
  <p class="resumo">{_e(item.resumo)}</p>
  <div class="grade">{"".join(figuras)}</div>
  <div class="rejeitar">{_comando(f"yt-thumbnail rejeitar {vid} --job {job}")}</div>
</section>"""


# --------------------------------------------------------------------------- aprovação


def _decidivel(r: RegistroVideo, forcar: bool) -> None:
    if ORDEM[r.status] < ORDEM["capas_compostas"]:
        raise ErroRevisao(f"{r.video_id}: ainda sem capas (status {r.status}); rode `compor`")
    if ORDEM[r.status] > ORDEM["aprovado"] and not forcar:
        raise ErroRevisao(
            f"{r.video_id}: já está como {r.status}; use --forcar para mudar a decisão"
        )


def aprovar(
    estado: Estado,
    pasta_saida: Path,
    job: str,
    video_id: str,
    variacao: int,
    *,
    forcar: bool = False,
) -> RegistroVideo:
    """Aprova a variação ``variacao`` (1, 2, 3...) de um vídeo."""
    r = estado.obter(job, video_id)
    if r is None:
        raise ErroRevisao(f"{video_id}: não está no job {job}")
    _decidivel(r, forcar)
    capas = ler_capas(pasta_video(pasta_saida, job, video_id))
    if capas is None:
        raise ErroRevisao(f"{video_id}: capas.json ausente ou incompleto; rode `compor`")
    if not 1 <= variacao <= len(capas.capas):
        raise ErroRevisao(f"{video_id}: variação {variacao} não existe (há {len(capas.capas)})")
    return estado.registrar(
        job,
        video_id,
        "aprovado",
        dados={
            "variacao": variacao,
            "capa": capas.capas[variacao - 1].arquivo,
            "decidido_em": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        permitir_regredir=forcar,
    )


def rejeitar(estado: Estado, job: str, video_id: str, *, forcar: bool = False) -> RegistroVideo:
    """Rejeita todas as variações de um vídeo (ele não será enviado)."""
    r = estado.obter(job, video_id)
    if r is None:
        raise ErroRevisao(f"{video_id}: não está no job {job}")
    _decidivel(r, forcar)
    return estado.registrar(
        job,
        video_id,
        "rejeitado",
        dados={
            "variacao": None,
            "capa": None,
            "decidido_em": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        permitir_regredir=forcar,
    )


def pendentes(estado: Estado, job: str, tipos: Iterable[str] | None = None) -> list[str]:
    """IDs com capas compostas ainda sem decisão."""
    filtro = set(tipos) if tipos is not None else None
    return [
        r.video_id
        for r in estado.listar(job, status="capas_compostas")
        if filtro is None or r.tipo in filtro
    ]


def localizar_jobs(estado: Estado, jobs: Iterable[str], video_id: str) -> list[str]:
    """Jobs (entre ``jobs``) em que o vídeo existe."""
    return [j for j in jobs if estado.obter(j, video_id) is not None]
