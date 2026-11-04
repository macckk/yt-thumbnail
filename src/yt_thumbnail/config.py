# SPDX-License-Identifier: GPL-3.0-or-later
"""Carga e validação do ``config.yaml`` (pydantic).

Referência das chaves: ``docs/configuracao.md``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from yt_thumbnail.presets import ErroPreset, Preset, carregar_preset

TipoVideo = Literal["longo", "short"]
_APELIDO = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_CHANNEL_ID = re.compile(r"^UC[0-9A-Za-z_-]{22}$")

CAMINHO_PADRAO = Path("config.yaml")


class ErroConfig(Exception):
    """Erro ao carregar ou validar a configuração."""


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Caminhos(_Modelo):
    """Pastas usadas pelo projeto (relativas à pasta do config.yaml)."""

    saida: Path = Path("saida")
    secrets: Path = Path("secrets")
    presets: Path = Path("presets")
    prompts: Path = Path("prompts")


class Gpu(_Modelo):
    """Índice da GPU de cada etapa."""

    transcricao: int = Field(0, ge=0)
    imagem: int = Field(1, ge=0)


class Transcricao(_Modelo):
    """Opções de transcrição (legenda do YouTube + fallback faster-whisper)."""

    idiomas: list[str] = Field(default_factory=lambda: ["pt.*", "pt"])
    modelo_whisper: str = "large-v3"
    compute_type: str = "float16"


class AnaliseCfg(_Modelo):
    """Opções do backend de análise."""

    backend: Literal["claude_code"] = "claude_code"
    tentativas: int = Field(2, ge=0, le=10)
    max_caracteres_transcricao: int = Field(20000, ge=1000)


class ImagemCfg(_Modelo):
    """Opções de geração de imagem (SDXL)."""

    modelo: str = "stabilityai/stable-diffusion-xl-base-1.0"
    variacoes: int = Field(3, ge=1, le=10)


class Formato(_Modelo):
    """Resolução de geração (SDXL) e de saída final, em pixels [largura, altura]."""

    geracao: tuple[int, int]
    saida: tuple[int, int]

    @field_validator("geracao")
    @classmethod
    def _multiplo_8(cls, v: tuple[int, int]) -> tuple[int, int]:
        if any(d % 8 or d <= 0 for d in v):
            raise ValueError("a resolução de geração do SDXL deve ser positiva e múltipla de 8")
        return v


class Formatos(_Modelo):
    """Formatos por tipo de vídeo."""

    longo: Formato = Formato(geracao=(1344, 768), saida=(1280, 720))
    short: Formato = Formato(geracao=(768, 1344), saida=(1080, 1920))


class Envio(_Modelo):
    """Opções de envio à API do YouTube."""

    pausa_segundos: tuple[float, float] = (5.0, 10.0)


class Canal(_Modelo):
    """Um canal próprio do usuário (um token OAuth por canal)."""

    channel_id: str | None = None
    shorts_capa_personalizada: bool = False

    @field_validator("channel_id")
    @classmethod
    def _id(cls, v: str | None) -> str | None:
        if v is not None and not _CHANNEL_ID.match(v):
            raise ValueError(
                f"channel_id {v!r} inválido (deve começar com 'UC' e ter 24 caracteres). "
                "Deixe em branco e rode `yt-thumbnail auth --canal <apelido>` para preencher."
            )
        return v


class Job(_Modelo):
    """Associação playlist → canal → preset."""

    nome: str
    playlist: str
    canal: str
    preset: str
    tipos: list[TipoVideo] = Field(default_factory=lambda: ["longo"])

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        if not _APELIDO.match(v):
            raise ValueError("nome do job: use só letras minúsculas, números, '-' e '_'")
        return v

    @field_validator("playlist")
    @classmethod
    def _playlist(cls, v: str) -> str:
        if "list=" not in v:
            raise ValueError(
                "playlist deve ser uma URL com 'list=' (ex.: https://www.youtube.com/playlist?list=...)"
            )
        return v

    @field_validator("tipos")
    @classmethod
    def _tipos(cls, v: list[TipoVideo]) -> list[TipoVideo]:
        if not v:
            raise ValueError("tipos não pode ser vazio; use [longo] ou [longo, short]")
        return list(dict.fromkeys(v))


class Config(_Modelo):
    """Configuração completa do yt-thumbnail."""

    caminhos: Caminhos = Field(default_factory=Caminhos)
    gpu: Gpu = Field(default_factory=Gpu)
    transcricao: Transcricao = Field(default_factory=Transcricao)
    analise: AnaliseCfg = Field(default_factory=AnaliseCfg)
    imagem: ImagemCfg = Field(default_factory=ImagemCfg)
    formatos: Formatos = Field(default_factory=Formatos)
    envio: Envio = Field(default_factory=Envio)
    canais: dict[str, Canal] = Field(default_factory=dict)
    jobs: list[Job] = Field(default_factory=list)

    base: Path = Field(default=Path("."), exclude=True)
    """Pasta do config.yaml; caminhos relativos são resolvidos a partir dela."""

    @field_validator("canais")
    @classmethod
    def _apelidos(cls, v: dict[str, Canal]) -> dict[str, Canal]:
        for apelido in v:
            if not _APELIDO.match(apelido):
                raise ValueError(
                    f"apelido de canal {apelido!r}: use só letras minúsculas, números, '-' e '_'"
                )
        return v

    @model_validator(mode="after")
    def _referencias(self) -> Config:
        nomes = [j.nome for j in self.jobs]
        repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
        if repetidos:
            raise ValueError(f"nomes de job repetidos: {', '.join(repetidos)}")
        for job in self.jobs:
            if job.canal not in self.canais:
                raise ValueError(
                    f"job {job.nome!r} usa o canal {job.canal!r}, que não está em `canais`. "
                    f"Canais definidos: {', '.join(self.canais) or 'nenhum'}"
                )
        return self

    def caminho(self, relativo: Path) -> Path:
        """Resolve um caminho da config em relação à pasta do config.yaml."""
        return relativo if relativo.is_absolute() else (self.base / relativo)

    @property
    def pasta_saida(self) -> Path:
        """Pasta de artefatos."""
        return self.caminho(self.caminhos.saida)

    @property
    def pasta_secrets(self) -> Path:
        """Pasta de segredos (client_secret.json e tokens/)."""
        return self.caminho(self.caminhos.secrets)

    @property
    def pasta_presets(self) -> Path:
        """Pasta de presets."""
        return self.caminho(self.caminhos.presets)

    def job(self, nome: str) -> Job:
        """Retorna o job pelo nome.

        Raises:
            ErroConfig: se não existir.
        """
        for j in self.jobs:
            if j.nome == nome:
                return j
        definidos = ", ".join(j.nome for j in self.jobs) or "nenhum"
        raise ErroConfig(f"Job {nome!r} não existe. Jobs definidos: {definidos}")

    def preset_do_job(self, job: Job) -> Preset:
        """Carrega o preset usado por um job."""
        return carregar_preset(job.preset, self.pasta_presets)

    def validar_presets(self) -> dict[str, Preset]:
        """Carrega todos os presets referenciados pelos jobs.

        Raises:
            ErroConfig: se algum preset estiver ausente ou inválido.
        """
        carregados: dict[str, Preset] = {}
        for job in self.jobs:
            if job.preset in carregados:
                continue
            try:
                carregados[job.preset] = self.preset_do_job(job)
            except ErroPreset as e:
                raise ErroConfig(f"Job {job.nome!r}: {e}") from e
        return carregados


def caminho_config(caminho: Path | None = None) -> Path:
    """Caminho do config: argumento > ``YT_THUMBNAIL_CONFIG`` > ``./config.yaml``."""
    if caminho is not None:
        return caminho
    env = os.environ.get("YT_THUMBNAIL_CONFIG")
    return Path(env) if env else CAMINHO_PADRAO


def carregar_config(caminho: Path | None = None, *, validar_presets: bool = True) -> Config:
    """Carrega e valida o ``config.yaml``.

    Args:
        caminho: arquivo de configuração; padrão em :func:`caminho_config`.
        validar_presets: se ``True``, também carrega e valida os presets dos jobs.

    Raises:
        ErroConfig: com mensagem dizendo o que corrigir.
    """
    arquivo = caminho_config(caminho)
    if not arquivo.is_file():
        raise ErroConfig(
            f"Arquivo de configuração {arquivo} não encontrado. "
            "Copie config.example.yaml para config.yaml e ajuste (ver docs/configuracao.md)."
        )
    try:
        dados = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ErroConfig(f"YAML inválido em {arquivo}: {e}") from e
    if not isinstance(dados, dict):
        raise ErroConfig(f"{arquivo} deve conter um mapeamento YAML (chave: valor) no topo.")
    try:
        cfg = Config.model_validate({**dados, "base": arquivo.resolve().parent})
    except ValidationError as e:
        raise ErroConfig(f"Configuração inválida em {arquivo}:\n{e}") from e
    if validar_presets:
        cfg.validar_presets()
    return cfg
