# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da CLI e da verificação de ambiente (sem GPU)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from yt_thumbnail import ambiente, cli
from yt_thumbnail.cli import app

runner = CliRunner()


def test_help() -> None:
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "ambiente" in r.output and "validar" in r.output


def test_versao() -> None:
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0
    assert "yt-thumbnail" in r.output


def test_validar_ok(projeto: Path) -> None:
    r = runner.invoke(app, ["validar", "--config", str(projeto / "config.yaml")])
    assert r.exit_code == 0, r.output
    assert "meditacoes" in r.output


def test_validar_erro(tmp_path: Path) -> None:
    r = runner.invoke(app, ["validar", "--config", str(tmp_path / "x.yaml")])
    assert r.exit_code == 1
    assert "config.example.yaml" in r.output


def test_listar_cli(projeto: Path, monkeypatch) -> None:
    from test_playlist import VIDEOS, FakeYtDlp
    from yt_thumbnail import playlist

    monkeypatch.setattr(playlist, "extrair_ytdlp", FakeYtDlp(VIDEOS))
    monkeypatch.setattr(playlist, "eh_url_shorts", lambda video_id: None)
    monkeypatch.setattr(cli, "console", Console(width=200))
    args = ["listar", "--config", str(projeto / "config.yaml")]
    r = runner.invoke(app, args)
    assert r.exit_code == 0, r.output
    assert "SHORT" in r.output and "fora do job" in r.output
    assert "4 novo(s)" in r.output
    r = runner.invoke(app, args)
    assert "0 novo(s), 4 já listado(s)" in r.output
    assert (projeto / "saida" / "meditacoes" / "short01" / "meta.json").is_file()
    r = runner.invoke(app, [*args, "--job", "nao-existe"])
    assert r.exit_code == 1


def test_fontes_ausentes(raiz: Path, tmp_path: Path) -> None:
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "espiritualidade.yaml").write_bytes(
        (raiz / "presets" / "espiritualidade.yaml").read_bytes()
    )
    itens = ambiente.verificar_fontes(tmp_path)
    principal = [i for i in itens if i.obrigatorio]
    assert principal and not principal[0].ok
    assert "baixar_fontes" in principal[0].dica


def test_ambiente_sai_com_erro_quando_falha(monkeypatch, tmp_path: Path) -> None:
    falha = ambiente.Item("X", False, "ausente", "faça algo")
    monkeypatch.setattr(ambiente, "verificar_tudo", lambda raiz: [falha])
    r = runner.invoke(app, ["ambiente", "--raiz", str(tmp_path)])
    assert r.exit_code == 1


def test_ambiente_ok(monkeypatch, tmp_path: Path) -> None:
    ok = ambiente.Item("X", True, "ok")
    aviso = ambiente.Item("Y", False, "opcional", obrigatorio=False)
    monkeypatch.setattr(ambiente, "verificar_tudo", lambda raiz: [ok, aviso])
    r = runner.invoke(app, ["ambiente", "--raiz", str(tmp_path)])
    assert r.exit_code == 0, r.output
