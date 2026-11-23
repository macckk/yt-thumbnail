# SPDX-License-Identifier: GPL-3.0-or-later
"""Fase 7 — autenticação OAuth por canal e envio das capas aprovadas (YouTube Data API v3).

- Um OAuth client do tipo "App para computador" (``secrets/client_secret.json``), criado por
  cada pessoa no próprio Google Cloud (ver ``docs/google-oauth.md``).
- Um token por canal em ``secrets/tokens/<channel_id>.json``.
- ``thumbnails.set`` só para vídeos aprovados, conferindo o canal do vídeo × o token.
- ``restaurar`` envia de volta ``capa_original.jpg`` (o backup da Fase 6).
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from yt_thumbnail.estado import Estado
from yt_thumbnail.playlist import ler_meta, pasta_video
from yt_thumbnail.revisao import (
    ORIGINAL,
    Baixador,
    ErroRevisao,
    backup_vertical,
    baixar_http,
)

ESCOPOS = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
"""``youtube.upload`` para ``thumbnails.set``; ``youtube.readonly`` para identificar o canal."""

CLIENT_SECRET = "client_secret.json"
LIMITE_CAPA = 2 * 1024 * 1024


class ErroYouTube(Exception):
    """Erro de autenticação ou da API que impede continuar."""


class ErroCota(ErroYouTube):
    """Cota diária da API esgotada: o lote para e continua amanhã."""


# --------------------------------------------------------------------------- autenticação


def caminho_client_secret(pasta_secrets: Path) -> Path:
    return pasta_secrets / CLIENT_SECRET


def caminho_token(pasta_secrets: Path, channel_id: str) -> Path:
    return pasta_secrets / "tokens" / f"{channel_id}.json"


def autenticar_navegador(pasta_secrets: Path, abrir_navegador: bool = True) -> Any:
    """Faz o login OAuth no navegador e devolve as credenciais (``google.oauth2``)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    segredo = caminho_client_secret(pasta_secrets)
    if not segredo.is_file():
        raise ErroYouTube(
            f"{segredo} não encontrado. Crie o OAuth client (App para computador) no Google Cloud "
            "e salve o JSON com esse nome (ver docs/google-oauth.md)."
        )
    fluxo = InstalledAppFlow.from_client_secrets_file(str(segredo), ESCOPOS)
    return fluxo.run_local_server(
        port=0,
        open_browser=abrir_navegador,
        authorization_prompt_message="Abra este endereço no navegador para autorizar: {url}",
        success_message="Autorização concluída. Pode fechar esta aba e voltar ao terminal.",
    )


def gravar_token(pasta_secrets: Path, channel_id: str, credenciais: Any) -> Path:
    destino = caminho_token(pasta_secrets, channel_id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(".tmp")
    temporario.write_text(credenciais.to_json(), encoding="utf-8")
    temporario.replace(destino)
    return destino


def carregar_credenciais(pasta_secrets: Path, channel_id: str) -> Any:
    """Lê o token do canal, renovando-o se preciso.

    Raises:
        ErroYouTube: sem token, ou token revogado/vencido (``invalid_grant``; no modo
            "Teste" do Google Cloud o login vale 7 dias).
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    arquivo = caminho_token(pasta_secrets, channel_id)
    if not arquivo.is_file():
        raise ErroYouTube(f"sem login para o canal {channel_id}; rode `yt-thumbnail auth`")
    credenciais = Credentials.from_authorized_user_file(str(arquivo), ESCOPOS)
    if not credenciais.valid:
        try:
            credenciais.refresh(Request())
        except RefreshError as e:
            raise ErroYouTube(
                f"o login do canal {channel_id} venceu ou foi revogado ({e}). Rode "
                '`yt-thumbnail auth` de novo. No modo "Teste" do Google Cloud isso acontece a '
                "cada 7 dias (ver docs/google-oauth.md)."
            ) from e
        arquivo.write_text(credenciais.to_json(), encoding="utf-8")
    return credenciais


def servico(credenciais: Any) -> Any:
    """Cliente da YouTube Data API v3."""
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=credenciais, cache_discovery=False)


@dataclass(frozen=True)
class Canal:
    """Canal do YouTube autorizado por um token."""

    channel_id: str
    titulo: str


def canal_do_token(api: Any) -> Canal:
    """Canal ao qual o token dá acesso (``channels.list mine=true``)."""
    resp = api.channels().list(part="snippet", mine=True).execute()
    itens = resp.get("items") or []
    if not itens:
        raise ErroYouTube(
            "esta conta Google não tem canal do YouTube (ou o canal não foi escolhido no login)"
        )
    return Canal(itens[0]["id"], itens[0]["snippet"]["title"])


def gravar_channel_id_no_config(arquivo: Path, apelido: str, channel_id: str) -> bool:
    """Troca ``channel_id: null`` do canal ``apelido`` no config.yaml, preservando o resto.

    Devolve ``True`` se alterou o arquivo.
    """
    linhas = arquivo.read_text(encoding="utf-8").splitlines(keepends=True)
    dentro_canais = dentro_apelido = False
    indent_apelido = -1
    for i, linha in enumerate(linhas):
        texto = linha.rstrip("\r\n")
        if not texto.strip() or texto.lstrip().startswith("#"):
            continue
        indent = len(texto) - len(texto.lstrip())
        if indent == 0:
            dentro_canais = texto.startswith("canais:")
            dentro_apelido = False
            continue
        if dentro_canais and re.match(rf"^\s+{re.escape(apelido)}:\s*(#.*)?$", texto):
            dentro_apelido, indent_apelido = True, indent
            continue
        if dentro_apelido and indent <= indent_apelido:
            dentro_apelido = False
        if dentro_apelido:
            m = re.match(r"^(\s+channel_id:\s*)(null|~|''|\"\")?(\s*(#.*)?)$", texto)
            if m and m.group(2) is not None:
                fim = linha[len(texto) :]
                linhas[i] = f"{m.group(1)}{channel_id}{m.group(3)}{fim}"
                arquivo.write_text("".join(linhas), encoding="utf-8")
                return True
    return False


# --------------------------------------------------------------------------- envio


class ApiCapas(Protocol):
    """O que o envio precisa da API (permite simular nos testes)."""

    def enviar_capa(self, video_id: str, arquivo: Path) -> dict[str, Any]: ...

    def canal_do_video(self, video_id: str) -> str | None: ...


class ApiYouTube:
    """Implementação real sobre ``googleapiclient``."""

    def __init__(self, api: Any) -> None:
        self.api = api

    def enviar_capa(self, video_id: str, arquivo: Path) -> dict[str, Any]:
        from googleapiclient.http import MediaFileUpload

        midia = MediaFileUpload(str(arquivo), mimetype="image/jpeg", resumable=False)
        return self.api.thumbnails().set(videoId=video_id, media_body=midia).execute()  # type: ignore[no-any-return]

    def canal_do_video(self, video_id: str) -> str | None:
        resp = self.api.videos().list(part="snippet", id=video_id).execute()
        itens = resp.get("items") or []
        return itens[0]["snippet"]["channelId"] if itens else None

    def ids_da_playlist(self, playlist_id: str) -> list[str]:
        """IDs dos vídeos públicos e não listados da playlist, em ordem (1 unidade por 50)."""
        return ids_da_playlist(self.api, playlist_id)


def ids_da_playlist(api: Any, playlist_id: str) -> list[str]:
    """``playlistItems.list`` paginado; pula vídeos privados e excluídos."""
    ids: list[str] = []
    pagina: str | None = None
    while True:
        resp = (
            api.playlistItems()
            .list(
                part="contentDetails,status",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=pagina,
            )
            .execute()
        )
        for item in resp.get("items") or []:
            privacidade = (item.get("status") or {}).get("privacyStatus")
            video_id = (item.get("contentDetails") or {}).get("videoId")
            if video_id and privacidade in ("public", "unlisted"):
                ids.append(video_id)
        pagina = resp.get("nextPageToken")
        if not pagina:
            return list(dict.fromkeys(ids))


def classificar_erro_http(e: Exception) -> tuple[int | None, str, str]:
    """(status HTTP, motivo, mensagem) de um ``HttpError`` da API."""
    status = getattr(getattr(e, "resp", None), "status", None)
    motivo, mensagem = "", str(e)
    conteudo = getattr(e, "content", None)
    if conteudo:
        try:
            erro = json.loads(conteudo)["error"]
            mensagem = erro.get("message", mensagem)
            motivo = (erro.get("errors") or [{}])[0].get("reason", "")
        except (ValueError, KeyError, TypeError):
            pass
    return (int(status) if status else None), motivo, mensagem


@dataclass
class ResultadoEnvio:
    """Resumo de :func:`enviar_job`."""

    enviados: list[str] = field(default_factory=list)
    simulados: list[str] = field(default_factory=list)
    nao_elegiveis: dict[str, str] = field(default_factory=dict)
    pulados: dict[str, str] = field(default_factory=dict)
    erros: dict[str, str] = field(default_factory=dict)
    parado_por: str | None = None


def _gravar_envio(pasta: Path, dados: dict[str, Any]) -> None:
    arquivo = pasta / "envio.json"
    historico = []
    if arquivo.is_file():
        try:
            historico = json.loads(arquivo.read_text(encoding="utf-8")).get("historico", [])
        except (ValueError, AttributeError):
            historico = []
    historico.append(dados)
    arquivo.write_text(
        json.dumps({**dados, "historico": historico}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def enviar_job(
    *,
    job: str,
    tipos: Iterable[str],
    pasta_saida: Path,
    estado: Estado,
    channel_id: str | None,
    shorts_capa_personalizada: bool,
    api: ApiCapas | None,
    dry_run: bool = False,
    ids: Iterable[str] | None = None,
    limite: int | None = None,
    pausa: tuple[float, float] = (5.0, 10.0),
    dormir: Callable[[float], None] = time.sleep,
    ao_progredir: Callable[[str, int, int], None] | None = None,
) -> ResultadoEnvio:
    """Envia as capas aprovadas do job ao YouTube.

    Regras de segurança, nesta ordem, para cada vídeo aprovado:

    1. o canal do vídeo (``meta.json``) precisa ser o canal do job (``channel_id``);
    2. o backup ``capa_original.jpg`` precisa existir (rode ``revisar``);
    3. Short em canal sem capa personalizada → ``nao_elegivel`` (não é erro);
    4. com ``dry_run`` nada é enviado.

    Um 403 num Short vira ``nao_elegivel``; cota esgotada para o lote; outros erros ficam no
    estado do vídeo e o lote continua. Pausa aleatória entre envios.
    """
    resultado = ResultadoEnvio()
    if not channel_id:
        raise ErroYouTube("canal sem channel_id no config.yaml; rode `yt-thumbnail auth`")
    tipos = set(tipos)
    filtro = set(ids) if ids else None
    aprovados = [
        r
        for r in estado.listar(job, status="aprovado")
        if r.tipo in tipos and (filtro is None or r.video_id in filtro)
    ]
    if limite is not None:
        aprovados = aprovados[:limite]
    enviados_agora = 0
    for i, r in enumerate(aprovados, start=1):
        if ao_progredir:
            ao_progredir(r.video_id, i, len(aprovados))
        pasta = pasta_video(pasta_saida, job, r.video_id)
        meta = ler_meta(pasta)
        capa = pasta / str(r.dados.get("capa") or "")
        if meta is None or not r.dados.get("capa") or not capa.is_file():
            msg = "capa aprovada ou meta.json ausente; rode `compor` e aprove de novo"
            estado.marcar_erro(job, r.video_id, "enviar", msg)
            resultado.erros[r.video_id] = msg
            continue
        canal_video = meta.channel_id or (api.canal_do_video(r.video_id) if api else None)
        if canal_video != channel_id:
            resultado.pulados[r.video_id] = (
                f"o vídeo é do canal {canal_video or 'desconhecido'}, "
                f"não do canal do job ({channel_id})"
            )
            continue
        if not (pasta / ORIGINAL).is_file():
            resultado.pulados[r.video_id] = "sem backup da capa atual; rode `revisar` antes"
            continue
        if capa.stat().st_size > LIMITE_CAPA:
            msg = f"{capa.name} tem mais de 2 MB"
            estado.marcar_erro(job, r.video_id, "enviar", msg)
            resultado.erros[r.video_id] = msg
            continue
        if meta.tipo == "short" and not shorts_capa_personalizada:
            motivo = "canal sem capa personalizada para Shorts (shorts_capa_personalizada: false)"
            resultado.nao_elegiveis[r.video_id] = motivo
            if not dry_run:
                estado.registrar(job, r.video_id, "nao_elegivel", dados={"motivo": motivo})
            continue
        if dry_run:
            resultado.simulados.append(r.video_id)
            continue
        assert api is not None
        if enviados_agora:
            dormir(random.uniform(*pausa))
        try:
            resposta = _enviar_com_retentativa(api, r.video_id, capa, dormir)
        except ErroCota as e:
            resultado.parado_por = str(e)
            estado.marcar_erro(job, r.video_id, "enviar", str(e))
            break
        except Exception as e:  # noqa: BLE001 - erro de um vídeo não derruba o lote
            status, motivo, mensagem = classificar_erro_http(e)
            if status == 403 and meta.tipo == "short":
                resultado.nao_elegiveis[r.video_id] = mensagem
                estado.registrar(job, r.video_id, "nao_elegivel", dados={"motivo": mensagem})
                continue
            msg = f"HTTP {status} {motivo}: {mensagem}" if status else mensagem
            estado.marcar_erro(job, r.video_id, "enviar", msg)
            resultado.erros[r.video_id] = msg
            continue
        enviados_agora += 1
        quando = _agora()
        _gravar_envio(
            pasta,
            {
                "acao": "enviar",
                "enviado_em": quando,
                "variacao": r.dados.get("variacao"),
                "arquivo": capa.name,
                "channel_id": channel_id,
                "resposta": resposta,
            },
        )
        estado.registrar(job, r.video_id, "enviado", dados={"enviado_em": quando})
        resultado.enviados.append(r.video_id)
    return resultado


def _enviar_com_retentativa(
    api: ApiCapas, video_id: str, capa: Path, dormir: Callable[[float], None]
) -> dict[str, Any]:
    """``thumbnails.set`` com backoff em 429/5xx; cota esgotada vira :class:`ErroCota`."""
    espera = 30.0
    for tentativa in range(4):
        try:
            return api.enviar_capa(video_id, capa)
        except Exception as e:
            status, motivo, mensagem = classificar_erro_http(e)
            if motivo in ("quotaExceeded", "dailyLimitExceeded"):
                raise ErroCota(f"cota diária da API esgotada ({mensagem}); continue amanhã") from e
            if status in (429, 500, 502, 503, 504) and tentativa < 3:
                dormir(espera)
                espera *= 2
                continue
            raise
    raise AssertionError("inalcançável")  # pragma: no cover


def restaurar_video(
    *,
    api: ApiCapas,
    estado: Estado,
    pasta_saida: Path,
    job: str,
    video_id: str,
    channel_id: str,
    baixar: Baixador = baixar_http,
) -> dict[str, Any]:
    """Envia de volta a capa original (``capa_original.jpg``) e marca o vídeo como rejeitado.

    Shorts recebem a versão vertical do backup (:func:`~yt_thumbnail.revisao.backup_vertical`);
    a escolha fica em ``envio.json`` (``arquivo`` e ``origem``).
    """
    pasta = pasta_video(pasta_saida, job, video_id)
    original = pasta / ORIGINAL
    meta = ler_meta(pasta)
    if meta is None or estado.obter(job, video_id) is None:
        raise ErroYouTube(f"{video_id}: não está no job {job}")
    if not original.is_file():
        raise ErroYouTube(f"{video_id}: sem {ORIGINAL} (o backup é feito por `revisar`)")
    if meta.channel_id and meta.channel_id != channel_id:
        raise ErroYouTube(f"{video_id}: é do canal {meta.channel_id}, não de {channel_id}")
    arquivo, origem = original, "backup"
    if meta.tipo == "short":
        try:
            arquivo, origem = backup_vertical(pasta, meta, baixar)
        except ErroRevisao as e:
            raise ErroYouTube(str(e)) from e
    resposta = _enviar_com_retentativa(api, video_id, arquivo, time.sleep)
    quando = _agora()
    _gravar_envio(
        pasta,
        {
            "acao": "restaurar",
            "enviado_em": quando,
            "arquivo": arquivo.name,
            "origem": origem,
            "resposta": resposta,
        },
    )
    estado.registrar(
        job,
        video_id,
        "rejeitado",
        dados={"variacao": None, "capa": None, "restaurado_em": quando},
        permitir_regredir=True,
    )
    return resposta
