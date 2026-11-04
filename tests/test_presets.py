# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de presets.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from yt_thumbnail.presets import ErroPreset, carregar_preset, listar_presets


def test_espiritualidade(raiz: Path) -> None:
    p = carregar_preset("espiritualidade", raiz / "presets")
    assert p.imagem.simbolos == "neutro"
    assert p.analise.titulo_palavras == (2, 5)
    assert "text" in p.imagem.negative_prompt
    assert p.tipografia.cor_escura == "#4A3F35"
    assert p.layouts.short.area_segura == (0.10, 0.33, 0.90, 0.66)


def test_listar(raiz: Path, tmp_path: Path) -> None:
    assert "espiritualidade" in listar_presets(raiz / "presets")
    assert listar_presets(tmp_path / "nada") == []


def _copiar(raiz: Path, destino: Path, alterar) -> None:
    dados = yaml.safe_load((raiz / "presets" / "espiritualidade.yaml").read_text(encoding="utf-8"))
    alterar(dados)
    (destino / "espiritualidade.yaml").write_text(yaml.safe_dump(dados), encoding="utf-8")


@pytest.mark.parametrize(
    ("alteracao", "trecho"),
    [
        (lambda d: d["tipografia"].update(cor_escura="marrom"), "#RRGGBB"),
        (lambda d: d["imagem"].update(simbolos="cristao"), "simbolos"),
        (lambda d: d["layouts"]["longo"].update(area_segura=[0.5, 0.1, 0.2, 0.9]), "area_segura"),
        (lambda d: d["analise"].update(titulo_palavras=[5, 2]), "titulo_palavras"),
        (lambda d: d.update(nome="outro"), "Deixe os dois iguais"),
        (lambda d: d["imagem"].update(cor="x"), "Extra inputs"),
    ],
)
def test_invalidos(raiz: Path, tmp_path: Path, alteracao, trecho: str) -> None:
    _copiar(raiz, tmp_path, alteracao)
    with pytest.raises(ErroPreset, match=trecho):
        carregar_preset("espiritualidade", tmp_path)


def test_ausente(tmp_path: Path) -> None:
    with pytest.raises(ErroPreset, match="não encontrado"):
        carregar_preset("x", tmp_path)
