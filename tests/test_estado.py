# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de estado.py."""

from __future__ import annotations

from pathlib import Path

from yt_thumbnail.estado import abrir_estado


def test_registrar_e_nao_regredir(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as e:
        e.registrar("j", "v1", "listado", tipo="longo", titulo="T", dados={"a": 1})
        e.registrar("j", "v1", "analisado")
        r = e.registrar("j", "v1", "listado", dados={"b": 2})
        assert r.status == "analisado"
        assert r.dados == {"a": 1, "b": 2}
        assert r.tipo == "longo" and r.titulo == "T"
        r = e.registrar("j", "v1", "listado", permitir_regredir=True)
        assert r.status == "listado"


def test_erro_nao_muda_status_e_conta_tentativas(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as e:
        e.registrar("j", "v1", "transcrito")
        e.marcar_erro("j", "v1", "analisar", "falhou")
        r = e.marcar_erro("j", "v1", "analisar", "falhou de novo")
        assert (r.status, r.erro, r.mensagem, r.tentativas) == (
            "transcrito",
            "analisar",
            "falhou de novo",
            2,
        )
        r = e.registrar("j", "v1", "analisado")
        assert r.erro is None and r.tentativas == 0


def test_erro_em_video_novo(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as e:
        r = e.marcar_erro("j", "v9", "listar", "privado")
        assert r.status == "listado" and r.erro == "listar"


def test_listar_filtros_e_persistencia(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as e:
        e.registrar("j", "a", "listado", tipo="longo")
        e.registrar("j", "b", "listado", tipo="short")
        e.registrar("outro", "c", "listado", tipo="longo")
    with abrir_estado(tmp_path) as e:
        assert {r.video_id for r in e.listar("j")} == {"a", "b"}
        assert [r.video_id for r in e.listar("j", tipo="short")] == ["b"]
        assert e.listar("j", status="enviado") == []
        assert e.obter("j", "zzz") is None
