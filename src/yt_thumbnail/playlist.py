# SPDX-License-Identifier: GPL-3.0-or-later
"""Fase 1 — listagem da playlist (yt-dlp, sem API key) e detecção de tipo longo/Short.

Para cada vídeo grava ``<saida>/<job>/<video_id>/meta.json`` e registra o status ``listado``.
Nenhuma mídia é baixada.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from yt_thumbnail.estado import Estado

TipoVideo = Literal["longo", "short"]

DURACAO_MAX_SHORT = 180
"""Shorts têm até 180 s (3 min)."""

Extrator = Callable[[str, dict[str, Any]], dict[str, Any]]
"""Assinatura de uma função que devolve o ``info_dict`` do yt-dlp para uma URL."""


class ErroPlaylist(Exception):
    """Erro ao listar a playlist (a playlist inteira falhou)."""


class Meta(BaseModel):
    """Conteúdo de ``meta.json``."""

    model_config = ConfigDict(extra="ignore")

    video_id: str
    titulo: str
    descricao: str = ""
    url: str
    duracao: float | None = None
    largura: int | None = None
    altura: int | None = None
    tipo: TipoVideo
    tipo_origem: Literal["dimensoes", "duracao", "url_shorts"] = "dimensoes"
    channel_id: str | None = None
    canal_nome: str | None = None
    thumbnail_url: str | None = None
    data_publicacao: str | None = None
    indice_playlist: int | None = None
    listado_em: str


@dataclass
class ResultadoListagem:
    """Resumo de uma execução de :func:`listar_job`."""

    novos: list[Meta] = field(default_factory=list)
    existentes: list[Meta] = field(default_factory=list)
    erros: dict[str, str] = field(default_factory=dict)
    canal_divergente: list[Meta] = field(default_factory=list)

    @property
    def todos(self) -> list[Meta]:
        """Vídeos listados com sucesso (novos + existentes), na ordem da playlist."""
        return sorted(self.novos + self.existentes, key=lambda m: m.indice_playlist or 0)


# --------------------------------------------------------------------------- yt-dlp


def opcoes_ytdlp(cookies_navegador: str | None = None) -> dict[str, Any]:
    """Opções base do yt-dlp (silencioso, sem download)."""
    opcoes: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noprogress": True,
    }
    if cookies_navegador:
        opcoes["cookiesfrombrowser"] = (cookies_navegador,)
    return opcoes


def extrair_ytdlp(url: str, opcoes: dict[str, Any]) -> dict[str, Any]:
    """Chama ``yt_dlp.YoutubeDL.extract_info`` (sem download) e devolve o info_dict saneado."""
    from yt_dlp import YoutubeDL

    with YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(info)  # type: ignore[no-any-return]


def url_video(video_id: str) -> str:
    """URL canônica de um vídeo."""
    return f"https://www.youtube.com/watch?v={video_id}"


def listar_entradas(url_playlist: str, extrair: Extrator, opcoes: dict[str, Any]) -> list[dict]:
    """Lista as entradas da playlist (equivale a ``yt-dlp --flat-playlist -J``).

    Raises:
        ErroPlaylist: se a playlist não puder ser lida.
    """
    try:
        info = extrair(url_playlist, {**opcoes, "extract_flat": "in_playlist"})
    except Exception as e:  # noqa: BLE001 - yt-dlp lança vários tipos
        raise ErroPlaylist(
            f"Não foi possível ler a playlist {url_playlist}: {e}. Confira se ela é pública "
            "(ou não listada) e atualize o yt-dlp: pip install -U yt-dlp"
        ) from e
    entradas = [e for e in (info.get("entries") or []) if e and e.get("id")]
    return entradas


# --------------------------------------------------------------------------- tipo


def dimensoes(info: dict[str, Any]) -> tuple[int | None, int | None]:
    """Largura e altura do vídeo, pelo formato escolhido ou pelo maior formato de vídeo."""
    largura, altura = info.get("width"), info.get("height")
    if largura and altura:
        return int(largura), int(altura)
    melhores = [
        f
        for f in info.get("formats") or []
        if f.get("width") and f.get("height") and f.get("vcodec") not in (None, "none")
    ]
    if not melhores:
        return None, None
    f = max(melhores, key=lambda f: f["width"] * f["height"])
    return int(f["width"]), int(f["height"])


def classificar(duracao: float | None, largura: int | None, altura: int | None) -> TipoVideo | None:
    """Regra da seção 3 do PLANO: Short = duração ≤ 180 s **e** formato vertical.

    Devolve ``None`` quando não dá para decidir (duração curta sem dimensões conhecidas).
    """
    if duracao is not None and duracao > DURACAO_MAX_SHORT:
        return "longo"
    if largura and altura:
        return "short" if (duracao is not None and altura > largura) else "longo"
    return None


def eh_url_shorts(video_id: str, timeout: float = 10) -> bool | None:
    """Pergunta ao YouTube se ``/shorts/<id>`` é um Short (200) ou redireciona (não é).

    Devolve ``None`` se não for possível decidir (sem rede, consentimento de cookies, etc.).
    """

    class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    abridor = urllib.request.build_opener(_SemRedirecionar)
    req = urllib.request.Request(
        f"https://www.youtube.com/shorts/{video_id}",
        method="HEAD",
        headers={"User-Agent": "Mozilla/5.0 (yt-thumbnail)"},
    )
    try:
        with abridor.open(req, timeout=timeout) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return False if 300 <= e.code < 400 else None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def montar_meta(
    info: dict[str, Any],
    indice: int | None,
    verificar_shorts: Callable[[str], bool | None] = eh_url_shorts,
) -> Meta:
    """Monta o :class:`Meta` de um vídeo a partir do info_dict completo do yt-dlp."""
    video_id = info["id"]
    duracao = info.get("duration")
    largura, altura = dimensoes(info)
    tipo = classificar(duracao, largura, altura)
    origem = "dimensoes" if (largura and altura) else "duracao"
    if tipo is None:
        resposta = verificar_shorts(video_id)
        tipo = "short" if resposta else "longo"
        origem = "url_shorts"
    data = info.get("upload_date")
    if data and len(data) == 8:
        data = f"{data[:4]}-{data[4:6]}-{data[6:]}"
    return Meta(
        video_id=video_id,
        titulo=info.get("title") or video_id,
        descricao=info.get("description") or "",
        url=url_video(video_id),
        duracao=duracao,
        largura=largura,
        altura=altura,
        tipo=tipo,
        tipo_origem=origem,  # type: ignore[arg-type]
        channel_id=info.get("channel_id"),
        canal_nome=info.get("channel") or info.get("uploader"),
        thumbnail_url=info.get("thumbnail"),
        data_publicacao=data,
        indice_playlist=indice,
        listado_em=datetime.now(UTC).isoformat(timespec="seconds"),
    )


# --------------------------------------------------------------------------- meta.json


def pasta_video(pasta_saida: Path, job: str, video_id: str) -> Path:
    """``<saida>/<job>/<video_id>/``."""
    return pasta_saida / job / video_id


def ler_meta(pasta: Path) -> Meta | None:
    """Lê ``meta.json`` da pasta do vídeo; ``None`` se não existir ou estiver inválido."""
    arquivo = pasta / "meta.json"
    if not arquivo.is_file():
        return None
    try:
        return Meta.model_validate_json(arquivo.read_text(encoding="utf-8"))
    except (ValidationError, ValueError):
        return None


def gravar_meta(pasta: Path, meta: Meta) -> Path:
    """Grava ``meta.json`` (UTF-8, indentado) e devolve o caminho."""
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "meta.json"
    temp = arquivo.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(meta.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(arquivo)
    return arquivo


# --------------------------------------------------------------------------- job


def listar_job(
    *,
    job: str,
    url_playlist: str,
    pasta_saida: Path,
    estado: Estado,
    channel_id_esperado: str | None = None,
    forcar: bool = False,
    ids: Iterable[str] | None = None,
    extrair: Extrator | None = None,
    opcoes: dict[str, Any] | None = None,
    verificar_shorts: Callable[[str], bool | None] | None = None,
    ao_progredir: Callable[[str, int, int], None] | None = None,
) -> ResultadoListagem:
    """Lista a playlist do job, grava ``meta.json`` e registra cada vídeo como ``listado``.

    Idempotente: vídeos com ``meta.json`` válido não são consultados de novo (a menos que
    ``forcar``). Erros por vídeo são registrados no estado sem interromper o lote.

    Raises:
        ErroPlaylist: se a própria playlist não puder ser lida.
    """
    extrair = extrair or extrair_ytdlp
    verificar_shorts = verificar_shorts or eh_url_shorts
    opcoes = opcoes if opcoes is not None else opcoes_ytdlp()
    filtro = set(ids) if ids else None
    entradas = listar_entradas(url_playlist, extrair, opcoes)
    resultado = ResultadoListagem()
    total = len(entradas)
    for indice, entrada in enumerate(entradas, start=1):
        video_id = entrada["id"]
        if filtro is not None and video_id not in filtro:
            continue
        if ao_progredir:
            ao_progredir(video_id, indice, total)
        pasta = pasta_video(pasta_saida, job, video_id)
        meta = None if forcar else ler_meta(pasta)
        if meta is not None:
            if meta.indice_playlist != indice:
                meta = meta.model_copy(update={"indice_playlist": indice})
                gravar_meta(pasta, meta)
            resultado.existentes.append(meta)
        else:
            try:
                info = extrair(url_video(video_id), opcoes)
                meta = montar_meta(info, indice, verificar_shorts)
            except Exception as e:  # noqa: BLE001 - não derruba o lote
                mensagem = str(e).strip() or e.__class__.__name__
                estado.marcar_erro(job, video_id, "listar", mensagem)
                resultado.erros[video_id] = mensagem
                continue
            gravar_meta(pasta, meta)
            resultado.novos.append(meta)
        estado.registrar(
            job,
            video_id,
            "listado",
            tipo=meta.tipo,
            titulo=meta.titulo,
            dados={"channel_id": meta.channel_id, "indice_playlist": indice},
            permitir_regredir=False,
        )
        if channel_id_esperado and meta.channel_id and meta.channel_id != channel_id_esperado:
            resultado.canal_divergente.append(meta)
    return resultado
