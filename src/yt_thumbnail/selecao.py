# SPDX-License-Identifier: GPL-3.0-or-later
"""Escolher quais vídeos ainda sem capa nova devem ganhar uma (``yt-thumbnail selecionar``).

Um vídeo **ignorado** sai da fila: nenhuma etapa (transcrever, analisar, gerar, compor,
revisar, enviar) o processa, e o ``listar`` não o traz de volta. ``incluir`` devolve o vídeo
à fila no ponto em que estava (as imagens já geradas são aproveitadas).

Só dá para ignorar vídeos que ainda não foram decididos na revisão (status de ``listado`` a
``capas_compostas``). A página ``selecao.html`` é montada na hora pelo servidor local
(:mod:`yt_thumbnail.servidor`), porque os botões precisam dele.
"""

from __future__ import annotations

import html
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from yt_thumbnail.estado import Estado, RegistroVideo
from yt_thumbnail.playlist import ler_meta, pasta_video
from yt_thumbnail.revisao import ORIGINAL, urls_capa

PAGINA_SELECAO = "selecao.html"
NA_FILA = ("listado", "transcrito", "analisado", "imagens_geradas", "capas_compostas")
_SITUACAO = {
    "listado": "na fila",
    "transcrito": "na fila (transcrito)",
    "analisado": "na fila (analisado)",
    "imagens_geradas": "na fila (imagens geradas)",
    "capas_compostas": "capas prontas, aguardando revisão",
}


class ErroSelecao(Exception):
    """Vídeo que não pode ser ignorado ou devolvido à fila."""


@dataclass(frozen=True)
class ItemSelecao:
    video_id: str
    titulo: str
    tipo: str
    status: str
    data_publicacao: str | None
    url: str
    capas: tuple[str, ...]
    """Endereços da capa atual, do melhor para o pior (o primeiro pode ser local)."""


def _item(pasta_saida: Path, job: str, r: RegistroVideo) -> ItemSelecao:
    pasta = pasta_video(pasta_saida, job, r.video_id)
    meta = ler_meta(pasta)
    tipo = r.tipo or (meta.tipo if meta else "longo")
    # A capa atual vem em 16:9; num Short, ela fica centralizada com as laterais desfocadas, e
    # o cartão vertical (object-fit: cover) mostra só o centro, que é a capa. Não usar o
    # oardefault.jpg: ele é o quadro do vídeo e não muda quando o Short ganha capa própria.
    capas = urls_capa(r.video_id, meta.thumbnail_url if meta else None)
    if (pasta / ORIGINAL).is_file():
        capas = [f"{r.video_id}/{ORIGINAL}", *capas]
    return ItemSelecao(
        video_id=r.video_id,
        titulo=(meta.titulo if meta else r.titulo) or r.video_id,
        tipo=tipo,
        status=r.status,
        data_publicacao=(meta.data_publicacao if meta else None) or r.dados.get("data_publicacao"),
        url=meta.url if meta else f"https://www.youtube.com/watch?v={r.video_id}",
        capas=tuple(capas),
    )


def itens_selecao(
    estado: Estado, pasta_saida: Path, job: str, tipos: Iterable[str]
) -> tuple[list[ItemSelecao], list[ItemSelecao]]:
    """(na fila, ignorados) do job, só dos ``tipos`` dados, mais recentes primeiro."""
    tipos = set(tipos)
    fila: list[ItemSelecao] = []
    ignorados: list[ItemSelecao] = []
    for r in estado.listar(job, tipo=None, incluir_ignorados=True):
        if r.tipo not in tipos:
            continue
        if r.status == "ignorado":
            ignorados.append(_item(pasta_saida, job, r))
        elif r.status in NA_FILA:
            fila.append(_item(pasta_saida, job, r))
    return fila, ignorados


def ignorar(estado: Estado, job: str, video_id: str) -> RegistroVideo:
    """Tira o vídeo da fila (não terá capa nova). Repetir não muda nada."""
    r = estado.obter(job, video_id)
    if r is None:
        raise ErroSelecao(f"{video_id} não está no job {job}; rode `listar`")
    if r.status == "ignorado":
        return r
    if r.status not in NA_FILA:
        raise ErroSelecao(f"{video_id}: já está {r.status}; só dá para ignorar antes da revisão")
    return estado.registrar(job, video_id, "ignorado", dados={"status_antes": r.status})


def incluir(estado: Estado, job: str, video_id: str) -> RegistroVideo:
    """Devolve um vídeo ignorado à fila, no ponto em que estava. Repetir não muda nada."""
    r = estado.obter(job, video_id)
    if r is None:
        raise ErroSelecao(f"{video_id} não está no job {job}; rode `listar`")
    if r.status in NA_FILA:
        return r
    if r.status != "ignorado":
        raise ErroSelecao(f"{video_id}: está {r.status}, não ignorado")
    antes = r.dados.get("status_antes")
    volta = antes if antes in NA_FILA else "listado"
    return estado.registrar(job, video_id, volta, permitir_regredir=True)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- página


def _e(texto: object) -> str:
    return html.escape(str(texto), quote=True)


def _data(iso: str | None) -> str:
    if not iso:
        return "sem data"
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return iso


def _cartao(item: ItemSelecao) -> str:
    alternativas = _e(json.dumps(list(item.capas[1:])))
    situacao = (
        "ignorado: fica com a capa atual"
        if item.status == "ignorado"
        else _SITUACAO.get(item.status, item.status)
    )
    busca = _e(item.titulo.lower())
    return f"""<label class="cartao {_e(item.tipo)}" data-busca="{busca}">
  <input type="checkbox" value="{_e(item.video_id)}">
  <span class="capa"><img src="{_e(item.capas[0])}" data-alt="{alternativas}"
    alt="Capa atual" loading="lazy" referrerpolicy="no-referrer"></span>
  <span class="info">
    <a href="{_e(item.url)}" target="_blank" rel="noopener">{_e(item.titulo)}</a>
    <span class="data">{_e(_data(item.data_publicacao))} ·
      {"Short" if item.tipo == "short" else "longo"}</span>
    <span class="situacao">{_e(situacao)}</span>
  </span>
</label>"""


def montar_pagina(job: str, fila: list[ItemSelecao], ignorados: list[ItemSelecao]) -> str:
    """Página de seleção (só funciona servida, por causa dos botões)."""
    cartoes_fila = "\n".join(_cartao(i) for i in fila) or (
        "<p class='vazio'>Nenhum vídeo na fila. Rode <code>yt-thumbnail listar</code> para "
        "buscar vídeos novos da playlist.</p>"
    )
    cartoes_ign = "\n".join(_cartao(i) for i in ignorados) or (
        "<p class='vazio'>Nenhum vídeo ignorado.</p>"
    )
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Escolher vídeos — {_e(job)}</title>
<style>
:root {{
  --fundo: #f6f2ea; --cartao: #fffdf8; --texto: #3b332b; --suave: #7a6e62; --borda: #e4dccd;
  --marcado: #a2463b; --ok: #2f7d4f; --barra: rgba(246, 242, 234, .96);
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --fundo: #1d1a17; --cartao: #262220; --texto: #ece5da; --suave: #a99d8f;
    --borda: #3a342f; --marcado: #e08a7f; --ok: #6fc28e; --barra: rgba(29, 26, 23, .96);
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--fundo); color: var(--texto);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
header, main {{ max-width: 1400px; margin: 0 auto; padding: 16px; }}
header h1 {{ margin: 8px 0 4px; font-size: 22px; }}
header p {{ margin: 4px 0; color: var(--suave); }}
.barra {{ position: sticky; top: 0; z-index: 2; background: var(--barra);
  border-bottom: 1px solid var(--borda); }}
.barra div {{ max-width: 1400px; margin: 0 auto; padding: 10px 16px; display: flex;
  flex-wrap: wrap; gap: 8px; align-items: center; }}
input[type=search] {{ flex: 1 1 220px; padding: 8px 10px; border-radius: 8px;
  border: 1px solid var(--borda); background: var(--cartao); color: var(--texto); font: inherit; }}
button {{ font: inherit; padding: 8px 12px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--borda); background: var(--cartao); color: var(--texto); }}
button.principal {{ background: var(--marcado); border-color: var(--marcado); color: #fff;
  font-weight: 600; }}
button.voltar {{ background: var(--ok); border-color: var(--ok); color: #fff; font-weight: 600; }}
button:disabled {{ opacity: .5; cursor: default; }}
h2 {{ font-size: 18px; margin: 20px 0 10px; }}
.grade {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px; }}
.cartao {{ position: relative; display: flex; flex-direction: column; gap: 6px;
  background: var(--cartao); border: 2px solid var(--borda); border-radius: 12px;
  padding: 8px; cursor: pointer; }}
.cartao:has(input:checked) {{ border-color: var(--marcado);
  box-shadow: 0 0 0 2px var(--marcado) inset; }}
.cartao input {{ position: absolute; top: 14px; left: 14px; width: 22px; height: 22px;
  z-index: 1; accent-color: var(--marcado); }}
.capa {{ display: block; aspect-ratio: 9 / 16; overflow: hidden; border-radius: 8px;
  background: var(--borda); }}
.cartao.longo .capa {{ aspect-ratio: 16 / 9; }}
.capa img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.cartao:has(input:checked) img {{ opacity: .55; }}
.info {{ display: flex; flex-direction: column; gap: 2px; font-size: 13px; }}
.info a {{ color: inherit; font-weight: 600; text-decoration: none; overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }}
.info a:hover {{ text-decoration: underline; }}
.data, .situacao {{ color: var(--suave); font-size: 12px; }}
.oculto {{ display: none; }}
.vazio {{ color: var(--suave); }}
details {{ margin-top: 28px; }}
summary {{ cursor: pointer; font-size: 18px; font-weight: 700; }}
#aviso {{ position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
  background: var(--texto); color: var(--fundo); padding: 10px 16px; border-radius: 10px;
  display: none; z-index: 3; }}
#sem-servidor {{ display: none; padding: 12px; border: 2px solid var(--marcado);
  border-radius: 10px; }}
body.sem-token #sem-servidor {{ display: block; }}
</style>
</head>
<body data-job="{_e(job)}">
<header>
  <h1>Escolher vídeos — {_e(job)}</h1>
  <p>Vídeos que ainda não ganharam capa nova, dos mais recentes para os mais antigos.
  <strong>Marque os que você NÃO quer trocar a capa</strong> e clique em
  <em>Não trocar a capa dos marcados</em>. Eles saem da fila e mantêm a capa atual.</p>
  <p>{len(fila)} vídeo(s) na fila · {len(ignorados)} ignorado(s). Clique no título para ver
  o vídeo no YouTube. A imagem é a capa atual.</p>
  <p id="sem-servidor">Esta página só funciona aberta por
  <code>yt-thumbnail selecionar</code> (o servidor local).</p>
</header>
<div class="barra"><div>
  <input type="search" id="filtro" placeholder="Filtrar pelo título...">
  <button type="button" data-marcar="fila">Marcar todos (visíveis)</button>
  <button type="button" data-desmarcar>Desmarcar</button>
  <button type="button" class="principal" data-acao="ignorar" data-de="fila">
    Não trocar a capa dos marcados (<span class="n" data-de="fila">0</span>)</button>
</div></div>
<main>
  <h2>Na fila para ganhar capa nova ({len(fila)})</h2>
  <div class="grade" id="fila">
{cartoes_fila}
  </div>
  <details id="caixa-ignorados"{" open" if ignorados and not fila else ""}>
    <summary>Ignorados: ficam com a capa atual ({len(ignorados)})</summary>
    <p>Marque os que você quer devolver à fila.
      <button type="button" class="voltar" data-acao="incluir" data-de="ignorados">
      Voltar para a fila os marcados (<span class="n" data-de="ignorados">0</span>)</button></p>
    <div class="grade" id="ignorados">
{cartoes_ign}
    </div>
  </details>
</main>
<div id="aviso" role="status"></div>
<script>
const token = document.querySelector('meta[name="yt-token"]')?.content;
if (!token) document.body.classList.add("sem-token");
const job = document.body.dataset.job;

document.querySelectorAll("img[data-alt]").forEach((img) => {{
  img.addEventListener("error", () => {{
    const alt = JSON.parse(img.dataset.alt || "[]");
    if (alt.length) {{ img.dataset.alt = JSON.stringify(alt.slice(1)); img.src = alt[0]; }}
  }});
}});

function marcados(de) {{
  return [...document.querySelectorAll(`#${{de}} input:checked`)].map((c) => c.value);
}}

function contar() {{
  document.querySelectorAll("span.n")
    .forEach((s) => (s.textContent = marcados(s.dataset.de).length));
}}

function avisar(texto) {{
  const a = document.getElementById("aviso");
  a.textContent = texto; a.style.display = "block";
}}

document.getElementById("filtro").addEventListener("input", (ev) => {{
  const q = ev.target.value.trim().toLowerCase();
  document.querySelectorAll(".cartao").forEach((c) =>
    c.classList.toggle("oculto", q !== "" && !c.dataset.busca.includes(q)));
}});

document.addEventListener("change", contar);

document.addEventListener("click", async (ev) => {{
  if (ev.target.closest(".info a")) {{ ev.stopPropagation(); return; }}
  const marcar = ev.target.closest("button[data-marcar]");
  if (marcar) {{
    document.querySelectorAll(`#${{marcar.dataset.marcar}} .cartao:not(.oculto) input`)
      .forEach((c) => (c.checked = true));
    contar(); return;
  }}
  if (ev.target.closest("button[data-desmarcar]")) {{
    document.querySelectorAll(".cartao input").forEach((c) => (c.checked = false));
    contar(); return;
  }}
  const b = ev.target.closest("button[data-acao]");
  if (!b) return;
  const videos = marcados(b.dataset.de);
  if (!videos.length) {{ avisar("Nenhum vídeo marcado."); return; }}
  const acao = b.dataset.acao;
  const pergunta = acao === "ignorar"
    ? `Tirar ${{videos.length}} vídeo(s) da fila? Eles ficam com a capa atual.`
    : `Devolver ${{videos.length}} vídeo(s) à fila?`;
  if (!confirm(pergunta)) return;
  document.querySelectorAll("button").forEach((x) => (x.disabled = true));
  try {{
    const r = await fetch(`/api/${{acao}}`, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json", "X-Token": token }},
      body: JSON.stringify({{ job, videos }}),
    }});
    const d = await r.json();
    if (!d.ok) throw new Error(d.mensagem);
    avisar(d.mensagem);
    setTimeout(() => location.reload(), 700);
  }} catch (e) {{
    alert("Não deu certo: " + e.message + ". O servidor (yt-thumbnail selecionar) " +
          "ainda está aberto?");
    document.querySelectorAll("button").forEach((x) => (x.disabled = false));
  }}
}});
</script>
</body>
</html>
"""
