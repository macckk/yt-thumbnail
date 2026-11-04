# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de config.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from yt_thumbnail.config import ErroConfig, carregar_config


def _editar(caminho: Path, alterar) -> None:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    alterar(dados)
    caminho.write_text(yaml.safe_dump(dados, allow_unicode=True), encoding="utf-8")


def test_exemplo_valido(projeto: Path) -> None:
    cfg = carregar_config(projeto / "config.yaml")
    assert [j.nome for j in cfg.jobs] == ["meditacoes"]
    assert cfg.jobs[0].tipos == ["longo"]
    assert cfg.canais["espiritual-principal"].shorts_capa_personalizada is False
    assert cfg.formatos.short.geracao == (768, 1344)
    assert cfg.pasta_saida == projeto.resolve() / "saida"
    assert "espiritualidade" in cfg.validar_presets()


def test_arquivo_ausente(tmp_path: Path) -> None:
    with pytest.raises(ErroConfig, match="config.example.yaml"):
        carregar_config(tmp_path / "nao-existe.yaml")


def test_variavel_de_ambiente(projeto: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YT_THUMBNAIL_CONFIG", str(projeto / "config.yaml"))
    assert carregar_config().jobs


def test_canal_inexistente(projeto: Path) -> None:
    arq = projeto / "config.yaml"
    _editar(arq, lambda d: d["jobs"][0].update(canal="outro"))
    with pytest.raises(ErroConfig, match="não está em `canais`"):
        carregar_config(arq)


def test_preset_inexistente(projeto: Path) -> None:
    arq = projeto / "config.yaml"
    _editar(arq, lambda d: d["jobs"][0].update(preset="nao-existe"))
    with pytest.raises(ErroConfig, match="não encontrado"):
        carregar_config(arq)
    assert carregar_config(arq, validar_presets=False).jobs[0].preset == "nao-existe"


def test_chave_desconhecida(projeto: Path) -> None:
    arq = projeto / "config.yaml"
    _editar(arq, lambda d: d.update(gpus={"x": 1}))
    with pytest.raises(ErroConfig, match="Extra inputs"):
        carregar_config(arq)


@pytest.mark.parametrize(
    ("alteracao", "trecho"),
    [
        (lambda d: d["jobs"][0].update(tipos=["medio"]), "tipos"),
        (lambda d: d["jobs"][0].update(tipos=[]), "não pode ser vazio"),
        (lambda d: d["jobs"][0].update(playlist="https://youtu.be/abc"), "list="),
        (lambda d: d["jobs"].append(dict(d["jobs"][0])), "repetidos"),
        (lambda d: d["canais"]["espiritual-principal"].update(channel_id="abc"), "channel_id"),
        (lambda d: d["formatos"]["longo"].update(geracao=[1000, 770]), "múltipla de 8"),
    ],
)
def test_invalidos(projeto: Path, alteracao, trecho: str) -> None:
    arq = projeto / "config.yaml"
    _editar(arq, alteracao)
    with pytest.raises(ErroConfig, match=trecho):
        carregar_config(arq)


def test_tipos_sem_duplicata(projeto: Path) -> None:
    arq = projeto / "config.yaml"
    _editar(arq, lambda d: d["jobs"][0].update(tipos=["longo", "short", "longo"]))
    assert carregar_config(arq).jobs[0].tipos == ["longo", "short"]


def test_channel_id_valido(projeto: Path) -> None:
    arq = projeto / "config.yaml"
    cid = "UC" + "a" * 22
    _editar(arq, lambda d: d["canais"]["espiritual-principal"].update(channel_id=cid))
    assert carregar_config(arq).canais["espiritual-principal"].channel_id == cid


def test_job_por_nome(projeto: Path) -> None:
    cfg = carregar_config(projeto / "config.yaml")
    assert cfg.job("meditacoes").canal == "espiritual-principal"
    with pytest.raises(ErroConfig, match="não existe"):
        cfg.job("x")
