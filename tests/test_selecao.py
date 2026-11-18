# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de selecao.py (escolher quais vídeos ganham capa nova) e da página servida."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from test_revisao import _meta, _video
from test_servidor import _get, _post
from yt_thumbnail.cli import app
from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.playlist import gravar_meta, pasta_video
from yt_thumbnail.revisao import pendentes
from yt_thumbnail.selecao import ErroSelecao, ignorar, incluir, itens_selecao, montar_pagina
from yt_thumbnail.servidor import ServidorRevisao

runner = CliRunner()


def _listado(saida: Path, estado, job: str, vid: str, tipo: str, data: str) -> None:
    gravar_meta(pasta_video(saida, job, vid), _meta(vid, tipo, thumb=f"https://t/{vid}.jpg"))
    estado.registrar(job, vid, "listado", tipo=tipo, dados={"data_publicacao": data})


def test_ignorar_e_incluir(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as e:
        e.registrar("j", "a", "analisado", tipo="short")
        e.registrar("j", "b", "aprovado", tipo="short")
        r = ignorar(e, "j", "a")
        assert r.status == "ignorado" and r.dados["status_antes"] == "analisado"
        assert ignorar(e, "j", "a").status == "ignorado"  # repetir não muda nada
        # nenhuma etapa vê o ignorado, e o `listar` não o traz de volta
        assert [x.video_id for x in e.listar("j")] == ["b"]
        e.registrar("j", "a", "listado", dados={"indice_playlist": 3})
        assert e.obter("j", "a").status == "ignorado"
        assert [x.video_id for x in e.listar("j", status="ignorado")] == ["a"]
        # volta no ponto em que estava
        assert incluir(e, "j", "a").status == "analisado"
        assert incluir(e, "j", "a").status == "analisado"
        with pytest.raises(ErroSelecao, match="antes da revisão"):
            ignorar(e, "j", "b")
        with pytest.raises(ErroSelecao, match="não ignorado"):
            incluir(e, "j", "b")
        with pytest.raises(ErroSelecao, match="listar"):
            ignorar(e, "j", "zzz")


def test_itens_selecao_separa_filtra_e_ordena(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as e:
        _listado(tmp_path, e, "j", "velho", "short", "2025-01-01")
        _listado(tmp_path, e, "j", "novo", "short", "2026-11-15")
        _listado(tmp_path, e, "j", "longo1", "longo", "2026-11-16")
        _listado(tmp_path, e, "j", "fora", "short", "2026-05-01")
        e.registrar("j", "enviado1", "enviado", tipo="short")
        ignorar(e, "j", "fora")
        fila, ign = itens_selecao(e, tmp_path, "j", ["short"])
    assert [i.video_id for i in fila] == ["novo", "velho"]
    assert [i.video_id for i in ign] == ["fora"]
    assert fila[0].capas[:2] == ("https://i.ytimg.com/vi/novo/oardefault.jpg", "https://t/novo.jpg")
    assert fila[0].data_publicacao == "2026-11-15"
    pagina = montar_pagina("j", fila, ign)
    assert "15/11/2026" in pagina and 'value="novo"' in pagina and "&lt;novo&gt;" in pagina


@pytest.fixture
def servidor(tmp_path: Path) -> Iterator[ServidorRevisao]:
    with abrir_estado(tmp_path) as e:
        _listado(tmp_path, e, "j", "s1", "longo", "2026-11-01")
        _listado(tmp_path, e, "j", "s2", "longo", "2026-11-02")
        _video(tmp_path, e, "j", "pronto")
    s = ServidorRevisao(tmp_path, {"j": ["longo"]}, 0, pagina_inicial="selecao.html")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def test_pagina_de_selecao_servida(servidor: ServidorRevisao) -> None:
    status, corpo = _get(servidor, "/")  # redireciona para a página inicial (seleção)
    pagina = corpo.decode("utf-8")
    assert status == 200 and f'content="{servidor.token}"' in pagina
    assert 'value="s1"' in pagina and 'value="pronto"' in pagina
    assert _get(servidor, "/j/revisao.html")[0] == 200  # a revisão continua disponível


def test_ignorar_e_incluir_pela_pagina(servidor: ServidorRevisao) -> None:
    status, r = _post(servidor, "ignorar", {"job": "j", "videos": ["s1", "pronto"]})
    assert status == 200 and r["ok"] and "2 vídeo(s)" in r["mensagem"]
    with abrir_estado(servidor.pasta_saida) as e:
        assert e.obter("j", "s1").status == "ignorado"
        assert pendentes(e, "j") == []  # o que já tinha capas sai da revisão
    revisao = (servidor.pasta_saida / "j" / "revisao.html").read_text("utf-8")
    assert "data-video='pronto'" not in revisao
    pagina = _get(servidor, "/j/selecao.html")[1].decode("utf-8")
    assert "Na fila para ganhar capa nova (1)" in pagina

    status, r = _post(servidor, "incluir", {"job": "j", "videos": ["pronto"]})
    assert status == 200
    with abrir_estado(servidor.pasta_saida) as e:
        assert e.obter("j", "pronto").status == "capas_compostas"


@pytest.mark.parametrize(
    "dados",
    [
        {"job": "j"},
        {"job": "j", "videos": []},
        {"job": "j", "videos": "s1"},
        {"job": "j", "videos": [1]},
        {"job": "j", "videos": ["nao-existe"]},
        {"job": "outro", "videos": ["s1"]},
    ],
)
def test_pedidos_invalidos(servidor: ServidorRevisao, dados: dict) -> None:
    status, r = _post(servidor, "ignorar", dados)
    assert status == 400 and not r["ok"]


def test_token_errado(servidor: ServidorRevisao) -> None:
    status, _ = _post(servidor, "ignorar", {"job": "j", "videos": ["s1"]}, token="x")
    assert status == 403


def test_cli_selecionar_por_ids(projeto: Path) -> None:
    cfg = str(projeto / "config.yaml")
    saida = projeto / "saida"
    with abrir_estado(saida) as e:
        _listado(saida, e, "meditacoes", "v1", "longo", "2026-11-01")
    r = runner.invoke(app, ["selecionar", "v1", "--ignorar", "-c", cfg])
    assert r.exit_code == 0, r.output
    with abrir_estado(saida) as e:
        assert e.obter("meditacoes", "v1").status == "ignorado"
    r = runner.invoke(app, ["selecionar", "v1", "--incluir", "-c", cfg])
    assert r.exit_code == 0, r.output
    with abrir_estado(saida) as e:
        assert e.obter("meditacoes", "v1").status == "listado"
    assert runner.invoke(app, ["selecionar", "v1", "-c", cfg]).exit_code != 0
    assert runner.invoke(app, ["selecionar", "--ignorar", "-c", cfg]).exit_code != 0
