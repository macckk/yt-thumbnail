# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do servidor local da revisão (revisar --servir)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from test_revisao import _video
from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.servidor import ServidorRevisao


@pytest.fixture
def servidor(tmp_path: Path) -> Iterator[ServidorRevisao]:
    with abrir_estado(tmp_path) as estado:
        for vid in ("a", "b", "c"):
            _video(tmp_path, estado, "j", vid)
    decisoes: list[str] = []
    s = ServidorRevisao(tmp_path, {"j": ["longo"]}, 0, ao_decidir=decisoes.append)
    s.decisoes = decisoes  # type: ignore[attr-defined]
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.shutdown()
    s.server_close()


def _get(s: ServidorRevisao, caminho: str, host: str | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(s.url() + caminho.lstrip("/"))
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(s: ServidorRevisao, acao: str, dados: dict, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        s.url() + f"api/{acao}",
        data=json.dumps(dados).encode(),
        headers={"Content-Type": "application/json", "X-Token": token or s.token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_serve_pagina_com_token_e_imagens(servidor: ServidorRevisao) -> None:
    status, corpo = _get(servidor, "/")  # um job só: redireciona para a página
    pagina = corpo.decode("utf-8")
    assert status == 200 and f'content="{servidor.token}"' in pagina
    assert "data-acao='aprovar' data-video='a' data-variacao='2'" in pagina
    assert _get(servidor, "/j/a/capa_1.jpg")[0] == 200
    # o arquivo em disco não leva o token
    assert servidor.token not in (servidor.pasta_saida / "j" / "revisao.html").read_text("utf-8")


@pytest.mark.parametrize(
    "caminho",
    ["/j/estado.db", "/estado.db", "/outro/revisao.html", "/j/../estado.db", "/j/a/meta.json"],
)
def test_nao_serve_fora_das_imagens(servidor: ServidorRevisao, caminho: str) -> None:
    assert _get(servidor, caminho)[0] == 404


def test_recusa_outro_host(servidor: ServidorRevisao) -> None:
    assert _get(servidor, "/j/revisao.html", host="exemplo.com")[0] == 403


def test_aprovar_rejeitar_pelos_botoes(servidor: ServidorRevisao) -> None:
    status, r = _post(servidor, "aprovar", {"job": "j", "video": "a", "variacao": 2})
    assert status == 200 and r["ok"] and r["restantes"] == 2
    status, r = _post(servidor, "rejeitar", {"job": "j", "video": "b"})
    assert status == 200 and r["restantes"] == 1
    pagina = (servidor.pasta_saida / "j" / "revisao.html").read_text("utf-8")
    assert "data-video='a'" not in pagina and "data-video='c'" in pagina

    status, r = _post(servidor, "aprovar", {"job": "j", "video": "c", "variacao": 9})
    assert status == 400 and "não existe" in r["mensagem"]
    status, r = _post(servidor, "aprovar-todos", {"job": "j", "variacao": 3})
    assert status == 200 and r["restantes"] == 0
    assert "Nenhum vídeo aguardando revisão" in _get(servidor, "/j/revisao.html")[1].decode()

    with abrir_estado(servidor.pasta_saida) as estado:
        assert estado.obter("j", "a").dados["variacao"] == 2
        assert estado.obter("j", "b").status == "rejeitado"
        assert estado.obter("j", "c").dados["variacao"] == 3
    assert servidor.decisoes == [  # type: ignore[attr-defined]
        "aprovado j/a: variação 2",
        "rejeitado j/b",
        "aprovados 1 vídeo(s) de j: variação 3",
    ]


def test_post_exige_token_e_job_valido(servidor: ServidorRevisao) -> None:
    status, r = _post(servidor, "aprovar", {"job": "j", "video": "a", "variacao": 1}, "errado")
    assert status == 403 and not r["ok"]
    assert _post(servidor, "aprovar", {"job": "x", "video": "a", "variacao": 1})[0] == 400
    assert _post(servidor, "apagar", {"job": "j", "video": "a"})[0] == 400
    assert _post(servidor, "aprovar", {"job": "j", "video": "a", "variacao": "z"})[0] == 400
    with abrir_estado(servidor.pasta_saida) as estado:
        assert estado.obter("j", "a").status == "capas_compostas"
