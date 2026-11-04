# SPDX-License-Identifier: GPL-3.0-or-later
"""Modelo e carregamento dos presets de identidade visual (``presets/<nome>.yaml``)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_COR_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ErroPreset(Exception):
    """Erro ao carregar ou validar um preset."""


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validar_cor(valor: str) -> str:
    if not _COR_HEX.match(valor):
        raise ValueError(f"cor inválida {valor!r}; use o formato #RRGGBB")
    return valor


def _validar_area(area: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = area
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError(
            "area_segura deve ser [x0, y0, x1, y1] com 0 <= x0 < x1 <= 1 e idem para y"
        )
    return area


class Analise(_Modelo):
    """Camada de análise: tom e restrições do título (usada pelo Claude)."""

    tom: str
    titulo_palavras: tuple[int, int] = (2, 5)
    proibido: list[str] = Field(default_factory=list)
    diretrizes_imagem: str = ""

    @field_validator("titulo_palavras")
    @classmethod
    def _faixa(cls, v: tuple[int, int]) -> tuple[int, int]:
        if not 1 <= v[0] <= v[1]:
            raise ValueError("titulo_palavras deve ser [mínimo, máximo] com 1 <= mínimo <= máximo")
        return v


class Imagem(_Modelo):
    """Camada de imagem: sufixo de estilo e parâmetros do SDXL."""

    estilo_sufixo: str
    negative_prompt: str
    paleta: list[str] = Field(default_factory=list)
    simbolos: Literal["neutro", "livre"] = "neutro"
    guidance_scale: float = Field(6.0, gt=0, le=20)
    passos: int = Field(30, ge=1, le=150)

    @field_validator("paleta")
    @classmethod
    def _cores(cls, v: list[str]) -> list[str]:
        return [_validar_cor(c) for c in v]


class Sombra(_Modelo):
    """Sombra suave atrás do texto."""

    blur: int = Field(8, ge=0)
    opacidade: float = Field(0.35, ge=0, le=1)


class Veu(_Modelo):
    """Véu translúcido atrás do texto, para legibilidade."""

    cor: str = "#FFF8EC"
    opacidade: float = Field(0.45, ge=0, le=1)
    tipo: Literal["gradiente", "solido", "nenhum"] = "gradiente"

    @field_validator("cor")
    @classmethod
    def _cor(cls, v: str) -> str:
        return _validar_cor(v)


class Tipografia(_Modelo):
    """Camada de tipografia (Pillow)."""

    fonte: Path
    fonte_alternativa: Path | None = None
    cor_escura: str = "#4A3F35"
    cor_clara: str = "#FFFFFF"
    sombra: Sombra = Field(default_factory=Sombra)
    veu: Veu = Field(default_factory=Veu)
    linhas_max: int = Field(3, ge=1, le=6)

    @field_validator("cor_escura", "cor_clara")
    @classmethod
    def _cores(cls, v: str) -> str:
        return _validar_cor(v)


class Layout(_Modelo):
    """Layout de um tipo de vídeo."""

    area_segura: tuple[float, float, float, float]

    @field_validator("area_segura")
    @classmethod
    def _area(cls, v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        return _validar_area(v)


class Layouts(_Modelo):
    """Layouts por tipo de vídeo."""

    longo: Layout
    short: Layout


class Preset(_Modelo):
    """Preset completo: análise + imagem + tipografia + layouts."""

    nome: str
    descricao: str = ""
    analise: Analise
    imagem: Imagem
    tipografia: Tipografia
    layouts: Layouts


def carregar_preset(nome: str, pasta: Path) -> Preset:
    """Carrega e valida ``<pasta>/<nome>.yaml``.

    Raises:
        ErroPreset: se o arquivo não existir, não for YAML válido ou não passar na validação.
    """
    caminho = pasta / f"{nome}.yaml"
    if not caminho.is_file():
        disponiveis = ", ".join(listar_presets(pasta)) or "nenhum"
        raise ErroPreset(
            f"Preset {nome!r} não encontrado em {caminho}. Presets disponíveis: {disponiveis}. "
            "Crie um copiando presets/espiritualidade.yaml (ver docs/presets.md)."
        )
    try:
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ErroPreset(f"YAML inválido em {caminho}: {e}") from e
    try:
        preset = Preset.model_validate(dados)
    except ValidationError as e:
        raise ErroPreset(f"Preset inválido em {caminho}:\n{e}") from e
    if preset.nome != nome:
        raise ErroPreset(
            f"O campo 'nome' de {caminho} é {preset.nome!r}, mas o arquivo se chama {nome!r}. "
            "Deixe os dois iguais."
        )
    return preset


def listar_presets(pasta: Path) -> list[str]:
    """Lista os nomes dos presets disponíveis na pasta."""
    if not pasta.is_dir():
        return []
    return sorted(p.stem for p in pasta.glob("*.yaml"))
