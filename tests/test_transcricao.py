# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de transcricao.py (yt-dlp e Whisper simulados)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.playlist import Meta, gravar_meta, pasta_video
from yt_thumbnail.transcricao import (
    escolher_idioma,
    ler_info,
    limpar_vtt,
    tem_fala,
    transcrever_job,
)

VTT_AUTO = """WEBVTT
Kind: captions
Language: pt

00:00:00.000 --> 00:00:02.000 align:start position:0%

Olá<00:00:00.500><c> amigos,</c><00:00:01.000><c> sejam</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
Olá amigos, sejam


00:00:02.010 --> 00:00:04.000 align:start position:0%
Olá amigos, sejam
bem-vindos<00:00:02.500><c> à</c><c> palestra</c>

00:00:04.000 --> 00:00:06.000
[Música]

00:00:06.000 --> 00:00:08.000
bem-vindos à palestra
hoje falaremos de &amp; esperança
"""

VTT_MANUAL = """WEBVTT

NOTE isto é um comentário
que ocupa duas linhas

1
00:00:01.000 --> 00:00:03.000
<i>A paz começa dentro de nós.</i>

2
00:00:03.500 --> 00:00:05.000
Cultive a gratidão todos os dias.
"""


def test_limpar_vtt_automatica() -> None:
    assert limpar_vtt(VTT_AUTO).splitlines() == [
        "Olá amigos, sejam",
        "bem-vindos à palestra",
        "hoje falaremos de & esperança",
    ]


def test_limpar_vtt_manual() -> None:
    assert limpar_vtt(VTT_MANUAL) == (
        "A paz começa dentro de nós.\nCultive a gratidão todos os dias."
    )


def test_tem_fala() -> None:
    assert not tem_fala("")
    assert not tem_fala("ah\nok")
    assert tem_fala("A paz começa dentro de nós.")


@pytest.mark.parametrize(
    ("disp", "esperado"),
    [
        (["en", "pt-BR", "pt"], "pt"),
        (["en", "pt-BR"], "pt-BR"),
        (["pt-orig", "pt", "en"], "pt"),
        (["pt-orig", "en"], "pt-orig"),
        (["en", "live_chat"], None),
        (["pt-PT"], "pt-PT"),
    ],
)
def test_escolher_idioma(disp, esperado) -> None:
    assert escolher_idioma(disp, ["pt", "pt-BR", "pt.*"]) == esperado


class FakeYtDlp:
    """Simula o yt-dlp: metadados com legendas e download do VTT."""

    def __init__(self, legendas: dict[str, dict[str, Any]]) -> None:
        self.legendas = legendas
        self.downloads: list[tuple[str, str]] = []

    def __call__(self, url: str, opcoes: dict[str, Any]) -> dict[str, Any]:
        vid = url.rsplit("=", 1)[1]
        cfg = self.legendas.get(vid, {})
        if opcoes.get("_baixar_legenda"):
            idioma = opcoes["subtitleslangs"][0]
            tipo = "manual" if opcoes.get("writesubtitles") else "auto"
            self.downloads.append((vid, tipo))
            destino = Path(opcoes["outtmpl"]["subtitle"].replace("%(ext)s", f"{idioma}.vtt"))
            destino.write_text(cfg[tipo], encoding="utf-8")
        return {
            "id": vid,
            "subtitles": {"pt": [{}]} if "manual" in cfg else {},
            "automatic_captions": {"pt": [{}], "en": [{}]} if "auto" in cfg else {},
        }


class FakeWhisper:
    modelo = "fake-large"

    def __init__(self, textos: dict[str, str]) -> None:
        self.textos = textos
        self.chamadas: list[str] = []

    def transcrever(self, audio: Path, idioma: str) -> str:
        vid = audio.parent.name
        self.chamadas.append(vid)
        assert idioma == "pt"
        return self.textos.get(vid, "")


def fake_baixar(video_id: str, pasta: Path, opcoes: dict[str, Any]) -> Path:
    audio = pasta / "audio.m4a"
    audio.write_bytes(b"\x00")
    return audio


def _preparar(tmp_path: Path, estado, videos: dict[str, str]) -> None:
    for vid, tipo in videos.items():
        gravar_meta(
            pasta_video(tmp_path, "j", vid),
            Meta(video_id=vid, titulo=vid, url="u", tipo=tipo, listado_em="x"),
        )
        estado.registrar("j", vid, "listado", tipo=tipo)


def test_transcrever_job_origens_e_idempotencia(tmp_path: Path) -> None:
    yt = FakeYtDlp(
        {"manual1": {"manual": VTT_MANUAL, "auto": VTT_AUTO}, "auto1": {"auto": VTT_AUTO}}
    )
    whisper = FakeWhisper({"sem_leg": "Bom dia a todos, vamos falar sobre o perdão hoje."})
    videos = {
        "manual1": "longo",
        "auto1": "longo",
        "sem_leg": "longo",
        "short_mudo": "short",
        "short_x": "short",
    }
    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, videos)
        kw = dict(
            job="j",
            tipos=["longo", "short"],
            pasta_saida=tmp_path,
            estado=estado,
            transcritor=whisper,
            idiomas=["pt", "pt.*"],
            opcoes={},
            extrair=yt,
            baixar=fake_baixar,
        )
        r = transcrever_job(**kw, ids=["manual1", "auto1", "sem_leg", "short_mudo"])
        assert r.feitos == {
            "manual1": "legenda_manual",
            "auto1": "legenda_auto",
            "sem_leg": "whisper",
            "short_mudo": "sem_fala",
        }
        assert not r.erros
        p = pasta_video(tmp_path, "j", "auto1")
        assert (p / "legenda.vtt").is_file()
        assert "bem-vindos à palestra" in (p / "transcricao.txt").read_text(encoding="utf-8")
        info = json.loads((p / "transcricao.json").read_text(encoding="utf-8"))
        assert info["origem"] == "legenda_auto" and info["idioma"] == "pt"
        # áudio apagado por padrão
        assert not (pasta_video(tmp_path, "j", "sem_leg") / "audio.m4a").exists()
        mudo = ler_info(pasta_video(tmp_path, "j", "short_mudo"))
        assert mudo is not None and mudo.caracteres == 0
        reg = estado.obter("j", "manual1")
        assert reg.status == "transcrito"
        assert reg.dados["transcricao_origem"] == "legenda_manual"

        # 2ª execução: só o que falta (short_x), com limite
        r2 = transcrever_job(**kw)
        assert list(r2.feitos) == ["short_x"] and len(r2.existentes) == 4
        assert yt.downloads.count(("manual1", "manual")) == 1

        # --forcar-whisper refaz pelo whisper
        r3 = transcrever_job(**kw, ids=["manual1"], forcar_whisper=True)
        assert r3.feitos == {"manual1": "sem_fala"}


def test_filtro_tipo_limite_e_erro(tmp_path: Path) -> None:
    def quebra(url: str, opcoes: dict) -> dict:
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, {"a": "longo", "b": "longo", "c": "short"})
        r = transcrever_job(
            job="j",
            tipos=["longo"],
            pasta_saida=tmp_path,
            estado=estado,
            transcritor=FakeWhisper({}),
            idiomas=["pt"],
            limite=1,
            whisper_se_legenda_falhar=False,
            extrair=quebra,
            baixar=fake_baixar,
        )
        assert list(r.erros) == ["a"] and "429" in r.erros["a"]
        reg = estado.obter("j", "a")
        assert reg.status == "listado" and reg.erro == "transcrever"
        assert estado.obter("j", "c").status == "listado"


def test_meta_ausente(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as estado:
        estado.registrar("j", "z", "listado", tipo="longo")
        r = transcrever_job(
            job="j",
            tipos=["longo"],
            pasta_saida=tmp_path,
            estado=estado,
            transcritor=FakeWhisper({}),
            idiomas=["pt"],
            extrair=lambda u, o: {},
            baixar=fake_baixar,
        )
        assert "listar" in r.erros["z"]


def test_legenda_429_cai_no_whisper(tmp_path: Path) -> None:
    def bloqueado(url: str, opcoes: dict) -> dict:
        if opcoes.get("_baixar_legenda"):
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return {"automatic_captions": {"pt": [{}]}}

    whisper = FakeWhisper({"v": "Hoje vamos refletir sobre a caridade e o amor."})
    kw = dict(
        job="j",
        tipos=["longo"],
        pasta_saida=tmp_path,
        transcritor=whisper,
        idiomas=["pt"],
        extrair=bloqueado,
        baixar=fake_baixar,
    )
    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, {"v": "longo"})
        r = transcrever_job(**kw, estado=estado, whisper_se_legenda_falhar=False)
        assert "429" in r.erros["v"] and not whisper.chamadas
        r = transcrever_job(**kw, estado=estado)
        assert r.feitos == {"v": "whisper"} and "429" in r.legenda_falhou["v"]
        info = ler_info(pasta_video(tmp_path, "j", "v"))
        assert info is not None and "429" in (info.legenda_erro or "")
        assert estado.obter("j", "v").dados["legenda_erro"].endswith("Too Many Requests")
