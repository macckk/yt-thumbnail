# SPDX-License-Identifier: GPL-3.0-or-later
"""Fase 2 — transcrição.

1. Legenda do YouTube via yt-dlp (manual tem preferência sobre a automática), limpa de
   timestamps, tags e linhas repetidas.
2. Sem legenda (ou com ``forcar_whisper``): baixa só o áudio e transcreve com faster-whisper
   na GPU de transcrição.
3. Sem fala (ex.: Short só com música): ``origem = sem_fala``; a análise usa título e descrição.

Artefatos em ``<saida>/<job>/<video_id>/``: ``legenda.vtt`` ou ``audio.*``, ``transcricao.txt``
e ``transcricao.json`` (origem, idioma, tamanho).
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

from yt_thumbnail.estado import ORDEM, Estado
from yt_thumbnail.playlist import Extrator, ler_meta, pasta_video, url_video

Origem = Literal["legenda_manual", "legenda_auto", "whisper", "sem_fala"]

MIN_CARACTERES_FALA = 20
"""Abaixo disso a transcrição é considerada vazia (ex.: só "[Música]")."""

_RUIDO = re.compile(r"^\s*[\[(][^\])]*[\])]\s*$")  # [Música], (aplausos)


class InfoTranscricao(BaseModel):
    """Conteúdo de ``transcricao.json``."""

    origem: Origem
    idioma: str | None = None
    caracteres: int
    palavras: int
    modelo: str | None = None
    legenda_erro: str | None = None
    """Motivo de a legenda não ter sido usada (ex.: HTTP 429), quando caiu no Whisper."""
    transcrito_em: str


@dataclass
class Legenda:
    """Legenda escolhida para um vídeo."""

    texto: str
    origem: Literal["legenda_manual", "legenda_auto"]
    idioma: str


class Transcritor(Protocol):
    """Transcreve um arquivo de áudio para texto."""

    modelo: str

    def transcrever(self, audio: Path, idioma: str) -> str:
        """Devolve o texto transcrito (vazio se não houver fala)."""
        ...


@dataclass
class ResultadoTranscricao:
    """Resumo de :func:`transcrever_job`."""

    feitos: dict[str, Origem] = field(default_factory=dict)
    existentes: list[str] = field(default_factory=list)
    erros: dict[str, str] = field(default_factory=dict)
    legenda_falhou: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- VTT


_TIMESTAMP = re.compile(r"^\s*(\d{2}:)?\d{2}:\d{2}[.,]\d{3}\s+-->")
_TAG = re.compile(r"<[^>]+>")


def limpar_vtt(conteudo: str) -> str:
    """Converte um WebVTT em texto corrido, uma frase por linha.

    Remove cabeçalho, ``NOTE``/``STYLE``, timestamps, tags (``<c>``, ``<00:00:01.000>``),
    marcações de ruído (``[Música]``) e as linhas repetidas típicas da legenda automática.
    """
    linhas: list[str] = []
    bloco_ignorado = False
    for bruta in conteudo.replace("﻿", "").splitlines():
        linha = bruta.strip()
        if not linha:
            bloco_ignorado = False
            continue
        if linha.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        if linha.startswith(("NOTE", "STYLE", "REGION")):
            bloco_ignorado = True
            continue
        if bloco_ignorado or _TIMESTAMP.match(linha) or linha.isdigit():
            continue
        texto = html.unescape(_TAG.sub("", linha)).strip()
        texto = re.sub(r"\s+", " ", texto)
        if not texto or _RUIDO.match(texto):
            continue
        # legenda automática repete a linha anterior no início do bloco seguinte
        if texto in linhas[-2:]:
            continue
        linhas.append(texto)
    return "\n".join(linhas)


def tem_fala(texto: str) -> bool:
    """``True`` se o texto tem conteúdo falado suficiente."""
    return len(re.sub(r"\W+", "", texto)) >= MIN_CARACTERES_FALA


# --------------------------------------------------------------------------- legendas


def escolher_idioma(disponiveis: Iterable[str], padroes: list[str]) -> str | None:
    """Primeiro idioma disponível que casa com os padrões, na ordem dos padrões.

    Os padrões são expressões regulares inteiras (como no ``--sub-langs`` do yt-dlp).
    Entre vários candidatos do mesmo padrão, prefere o mais curto (``pt`` antes de ``pt-BR``).
    """
    chaves = sorted({d for d in disponiveis if d != "live_chat"}, key=lambda k: (len(k), k))
    for padrao in padroes:
        candidatos = [k for k in chaves if re.fullmatch(padrao, k)]
        if candidatos:
            return candidatos[0]
    return None


def obter_legenda(
    video_id: str,
    pasta: Path,
    idiomas: list[str],
    extrair: Extrator,
    opcoes: dict[str, Any],
) -> Legenda | None:
    """Baixa a melhor legenda (manual > automática) em VTT para ``pasta/legenda.vtt``.

    Devolve ``None`` se não houver legenda nos idiomas pedidos ou se ela estiver vazia.
    """
    info = extrair(url_video(video_id), opcoes)
    for chave, origem, flag in (
        ("subtitles", "legenda_manual", "writesubtitles"),
        ("automatic_captions", "legenda_auto", "writeautomaticsub"),
    ):
        faixas: dict[str, Any] = info.get(chave) or {}
        idioma = escolher_idioma(faixas, idiomas)
        if idioma is None:
            continue
        pasta.mkdir(parents=True, exist_ok=True)
        for antigo in pasta.glob("legenda*.vtt"):
            antigo.unlink()
        extrair(
            url_video(video_id),
            {
                **opcoes,
                flag: True,
                "subtitleslangs": [idioma],
                "subtitlesformat": "vtt",
                "outtmpl": {
                    "subtitle": str(pasta / "legenda.%(ext)s"),
                    "default": str(pasta / "video.%(ext)s"),
                },
                "_baixar_legenda": True,
            },
        )
        arquivos = sorted(pasta.glob("legenda*.vtt"))
        if not arquivos:
            continue
        destino = pasta / "legenda.vtt"
        if arquivos[0] != destino:
            arquivos[0].replace(destino)
        texto = limpar_vtt(destino.read_text(encoding="utf-8", errors="replace"))
        if tem_fala(texto):
            return Legenda(texto=texto, origem=origem, idioma=idioma)  # type: ignore[arg-type]
    return None


def extrair_ytdlp_legenda(url: str, opcoes: dict[str, Any]) -> dict[str, Any]:
    """Como :func:`playlist.extrair_ytdlp`, mas baixando legendas quando pedido."""
    from yt_dlp import YoutubeDL

    baixar = bool(opcoes.get("_baixar_legenda"))
    opcoes = {k: v for k, v in opcoes.items() if k != "_baixar_legenda"}
    with YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=baixar)
        return ydl.sanitize_info(info)  # type: ignore[no-any-return]


# --------------------------------------------------------------------------- áudio + whisper


def baixar_audio(video_id: str, pasta: Path, opcoes: dict[str, Any]) -> Path:
    """Baixa só o áudio (``bestaudio``) para ``pasta/audio.<ext>`` e devolve o caminho."""
    from yt_dlp import YoutubeDL

    pasta.mkdir(parents=True, exist_ok=True)
    for antigo in pasta.glob("audio.*"):
        antigo.unlink()
    ops = {
        **opcoes,
        "skip_download": False,
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(pasta / "audio.%(ext)s"),
    }
    with YoutubeDL(ops) as ydl:
        ydl.extract_info(url_video(video_id), download=True)
    arquivos = [p for p in pasta.glob("audio.*") if not p.name.endswith(".part")]
    if not arquivos:
        raise RuntimeError("o yt-dlp não gerou o arquivo de áudio")
    return arquivos[0]


def preparar_dlls_cuda() -> None:
    """No Windows, expõe as DLLs de cuBLAS/cuDNN dos pacotes ``nvidia-*-cu12`` ao CTranslate2."""
    if sys.platform != "win32":
        return
    for base in map(Path, sys.path):
        nvidia = base / "nvidia"
        if not nvidia.is_dir():
            continue
        for bin_dir in nvidia.glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


TAXA_AMOSTRAGEM = 16000


def decodificar_audio(audio: Path, ffmpeg: str | None = None) -> Any:
    """Decodifica o áudio com o FFmpeg para mono 16 kHz ``float32`` (array do NumPy).

    Evita depender da versão do PyAV usada internamente pelo faster-whisper.

    Raises:
        RuntimeError: se o FFmpeg não estiver no PATH ou falhar.
    """
    import shutil
    import subprocess

    import numpy as np

    exe = ffmpeg or shutil.which("ffmpeg")
    if exe is None:
        raise RuntimeError(
            "FFmpeg não encontrado no PATH; instale com `winget install Gyan.FFmpeg` "
            "e reabra o terminal"
        )
    cmd = [exe, "-nostdin", "-v", "error", "-i", str(audio)]
    cmd += ["-f", "s16le", "-ac", "1", "-ar", str(TAXA_AMOSTRAGEM), "-"]
    r = subprocess.run(cmd, capture_output=True, check=False)
    if r.returncode != 0:
        erro = r.stderr.decode(errors="replace").strip()[-300:]
        raise RuntimeError(f"FFmpeg não conseguiu decodificar {audio.name}: {erro}")
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0


class TranscritorWhisper:
    """faster-whisper na GPU indicada; o modelo é carregado uma vez, no primeiro uso."""

    def __init__(self, modelo: str, gpu: int, compute_type: str = "float16") -> None:
        self.modelo = modelo
        self.gpu = gpu
        self.compute_type = compute_type
        self._whisper: Any = None

    def _carregar(self) -> Any:
        if self._whisper is None:
            preparar_dlls_cuda()
            from faster_whisper import WhisperModel

            self._whisper = WhisperModel(
                self.modelo,
                device="cuda",
                device_index=self.gpu,
                compute_type=self.compute_type,
            )
        return self._whisper

    def transcrever(self, audio: Path, idioma: str) -> str:
        """Transcreve com VAD; devolve um segmento por linha."""
        sinal = decodificar_audio(audio)
        if sinal.size == 0:
            return ""
        segmentos, _info = self._carregar().transcribe(
            sinal, language=idioma, vad_filter=True, beam_size=5
        )
        return "\n".join(s.text.strip() for s in segmentos if s.text.strip())


# --------------------------------------------------------------------------- arquivos


def ler_info(pasta: Path) -> InfoTranscricao | None:
    """Lê ``transcricao.json``; ``None`` se faltar ele ou o ``transcricao.txt``."""
    arquivo = pasta / "transcricao.json"
    if not arquivo.is_file() or not (pasta / "transcricao.txt").is_file():
        return None
    try:
        return InfoTranscricao.model_validate_json(arquivo.read_text(encoding="utf-8"))
    except (ValidationError, ValueError):
        return None


def gravar_transcricao(
    pasta: Path,
    texto: str,
    origem: Origem,
    idioma: str | None,
    modelo: str | None = None,
    legenda_erro: str | None = None,
) -> InfoTranscricao:
    """Grava ``transcricao.txt`` e ``transcricao.json``."""
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "transcricao.txt").write_text(texto + ("\n" if texto else ""), encoding="utf-8")
    info = InfoTranscricao(
        origem=origem,
        idioma=idioma,
        caracteres=len(texto),
        palavras=len(texto.split()),
        modelo=modelo,
        legenda_erro=legenda_erro,
        transcrito_em=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    (pasta / "transcricao.json").write_text(
        json.dumps(info.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return info


# --------------------------------------------------------------------------- job


def transcrever_video(
    video_id: str,
    pasta: Path,
    *,
    idiomas: list[str],
    idioma_whisper: str,
    transcritor: Transcritor,
    opcoes: dict[str, Any],
    forcar_whisper: bool = False,
    whisper_se_legenda_falhar: bool = True,
    manter_audio: bool = False,
    extrair: Extrator | None = None,
    baixar: Callable[[str, Path, dict[str, Any]], Path] | None = None,
) -> InfoTranscricao:
    """Transcreve um vídeo (legenda → whisper → sem_fala) e grava os artefatos.

    Se o download da legenda falhar (ex.: HTTP 429) e ``whisper_se_legenda_falhar``, segue
    pelo Whisper e registra o motivo em ``legenda_erro``; senão, propaga o erro.
    """
    extrair = extrair or extrair_ytdlp_legenda
    baixar = baixar or baixar_audio
    legenda_erro: str | None = None
    if not forcar_whisper:
        try:
            legenda = obter_legenda(video_id, pasta, idiomas, extrair, opcoes)
        except Exception as e:
            if not whisper_se_legenda_falhar:
                raise
            legenda, legenda_erro = None, (str(e).strip() or e.__class__.__name__)
        if legenda is not None:
            return gravar_transcricao(pasta, legenda.texto, legenda.origem, legenda.idioma)
    audio = baixar(video_id, pasta, opcoes)
    try:
        texto = transcritor.transcrever(audio, idioma_whisper).strip()
    finally:
        if not manter_audio:
            audio.unlink(missing_ok=True)
    if tem_fala(texto):
        return gravar_transcricao(
            pasta, texto, "whisper", idioma_whisper, transcritor.modelo, legenda_erro
        )
    return gravar_transcricao(pasta, "", "sem_fala", None, transcritor.modelo, legenda_erro)


def transcrever_job(
    *,
    job: str,
    tipos: Iterable[str],
    pasta_saida: Path,
    estado: Estado,
    transcritor: Transcritor,
    idiomas: list[str],
    idioma_whisper: str = "pt",
    opcoes: dict[str, Any] | None = None,
    ids: Iterable[str] | None = None,
    forcar: bool = False,
    forcar_whisper: bool = False,
    whisper_se_legenda_falhar: bool = True,
    manter_audio: bool = False,
    limite: int | None = None,
    extrair: Extrator | None = None,
    baixar: Callable[[str, Path, dict[str, Any]], Path] | None = None,
    ao_progredir: Callable[[str, int, int], None] | None = None,
) -> ResultadoTranscricao:
    """Transcreve os vídeos listados do job cujo tipo está em ``tipos``.

    Idempotente: pula vídeos com ``transcricao.txt``/``.json`` válidos, a menos que ``forcar``
    ou ``forcar_whisper`` (este refaz só pelo whisper). Erros ficam no estado.
    """
    tipos = set(tipos)
    filtro = set(ids) if ids else None
    opcoes = dict(opcoes or {})
    candidatos = [
        r
        for r in estado.listar(job)
        if r.tipo in tipos and (filtro is None or r.video_id in filtro)
    ]
    resultado = ResultadoTranscricao()
    pendentes = []
    for r in candidatos:
        pasta = pasta_video(pasta_saida, job, r.video_id)
        existente = None if (forcar or forcar_whisper) else ler_info(pasta)
        if existente is not None:
            resultado.existentes.append(r.video_id)
            if ORDEM[r.status] < ORDEM["transcrito"]:
                estado.registrar(job, r.video_id, "transcrito")
            continue
        pendentes.append(r)
    if limite is not None:
        pendentes = pendentes[:limite]
    for i, r in enumerate(pendentes, start=1):
        if ao_progredir:
            ao_progredir(r.video_id, i, len(pendentes))
        pasta = pasta_video(pasta_saida, job, r.video_id)
        if ler_meta(pasta) is None:
            msg = "meta.json ausente; rode `yt-thumbnail listar` antes"
            estado.marcar_erro(job, r.video_id, "transcrever", msg)
            resultado.erros[r.video_id] = msg
            continue
        try:
            info = transcrever_video(
                r.video_id,
                pasta,
                idiomas=idiomas,
                idioma_whisper=idioma_whisper,
                transcritor=transcritor,
                opcoes=opcoes,
                forcar_whisper=forcar_whisper,
                whisper_se_legenda_falhar=whisper_se_legenda_falhar,
                manter_audio=manter_audio,
                extrair=extrair,
                baixar=baixar,
            )
        except Exception as e:  # noqa: BLE001 - não derruba o lote
            msg = str(e).strip() or e.__class__.__name__
            estado.marcar_erro(job, r.video_id, "transcrever", msg)
            resultado.erros[r.video_id] = msg
            continue
        estado.registrar(
            job,
            r.video_id,
            "transcrito",
            dados={"transcricao_origem": info.origem, "legenda_erro": info.legenda_erro},
            permitir_regredir=forcar or forcar_whisper,
        )
        resultado.feitos[r.video_id] = info.origem
        if info.legenda_erro:
            resultado.legenda_falhou[r.video_id] = info.legenda_erro
    return resultado
