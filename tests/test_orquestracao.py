# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de orquestracao.py e do comando `tudo` (etapas simuladas)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from yt_thumbnail import cli
from yt_thumbnail.cli import app
from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.orquestracao import ETAPAS, arquivo_log, resumir

runner = CliRunner()


def test_arquivo_log(tmp_path: Path) -> None:
    caminho = arquivo_log(tmp_path, datetime(2026, 11, 16, 9, 5, 3))
    assert caminho == tmp_path / "logs" / "tudo-20261116-090503.log"


def test_resumir(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as estado:
        estado.registrar("j", "a", "capas_compostas", tipo="longo")
        estado.registrar("j", "b", "aprovado", tipo="longo")
        estado.registrar("j", "c", "nao_elegivel", tipo="short")
        estado.registrar("j", "d", "analisado", tipo="longo")
        estado.marcar_erro("j", "d", "gerar", "CUDA out of memory\nlinha 2")
        estado.registrar("outro", "z", "enviado", tipo="longo")
        r = resumir(estado, "j")
        assert r.total == 4
        assert r.pendentes_revisao == 1 and r.aprovados == 1
        assert r.chegaram_a_revisao == 3
        assert r.nao_elegiveis == ["c"]
        assert r.erros == {"d": ("gerar", "CUDA out of memory")}
        assert resumir(estado, "j", {"longo"}).total == 3


@pytest.fixture
def etapas_falsas(monkeypatch):
    chamadas: list[str] = []

    def falsa(nome: str, falhar: int | None = None):
        def etapa(**kw):
            chamadas.append(nome)
            if falhar is not None:
                raise typer.Exit(falhar)

        return etapa

    for nome in ETAPAS:
        monkeypatch.setattr(cli, nome, falsa(nome))
    return chamadas, falsa, monkeypatch


def test_tudo_roda_em_ordem_e_grava_log(projeto: Path, etapas_falsas) -> None:
    chamadas, _, _ = etapas_falsas
    cfg = str(projeto / "config.yaml")
    with abrir_estado(projeto / "saida") as estado:
        estado.registrar("meditacoes", "v1", "capas_compostas", tipo="longo")
    r = runner.invoke(app, ["tudo", "-c", cfg])
    assert r.exit_code == 0, r.output
    assert chamadas == list(ETAPAS)
    assert "aguardando revisão" in r.output
    logs = list((projeto / "saida" / "logs").glob("tudo-*.log"))
    assert len(logs) == 1
    texto = logs[0].read_text(encoding="utf-8")
    assert "transcrever" in texto and "resumo" in texto


def test_tudo_continua_depois_de_erro_e_para_em_ate(projeto: Path, etapas_falsas) -> None:
    chamadas, falsa, monkeypatch = etapas_falsas
    monkeypatch.setattr(cli, "transcrever", falsa("transcrever", falhar=1))
    cfg = str(projeto / "config.yaml")
    r = runner.invoke(app, ["tudo", "--ate", "gerar", "-c", cfg])
    assert r.exit_code == 1
    assert chamadas == ["listar", "transcrever", "analisar", "gerar"]
    assert "com erros" in r.output


def test_tudo_para_em_erro_de_uso(projeto: Path, etapas_falsas) -> None:
    chamadas, falsa, monkeypatch = etapas_falsas
    monkeypatch.setattr(cli, "listar", falsa("listar", falhar=2))
    r = runner.invoke(app, ["tudo", "-c", str(projeto / "config.yaml")])
    assert r.exit_code == 2 and chamadas == ["listar"]
    assert list((projeto / "saida" / "logs").glob("tudo-*.log"))  # log gravado mesmo assim


def test_tudo_mostra_erros_do_estado(projeto: Path, etapas_falsas) -> None:
    with abrir_estado(projeto / "saida") as estado:
        estado.registrar("meditacoes", "v9", "analisado", tipo="longo")
        estado.marcar_erro("meditacoes", "v9", "gerar", "sem memória")
    r = runner.invoke(app, ["tudo", "-c", str(projeto / "config.yaml")])
    assert r.exit_code == 1
    assert "meditacoes/v9 (gerar): sem memória" in r.output


def test_tudo_ate_invalido(projeto: Path) -> None:
    r = runner.invoke(app, ["tudo", "--ate", "enviar", "-c", str(projeto / "config.yaml")])
    assert r.exit_code != 0
