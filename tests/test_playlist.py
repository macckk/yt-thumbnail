# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de playlist.py (yt-dlp simulado, sem rede)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.playlist import (
    ErroPlaylist,
    classificar,
    dimensoes,
    listar_job,
    montar_meta,
)

PLAYLIST = "https://www.youtube.com/playlist?list=PLteste"
CANAL = "UC" + "x" * 22

VIDEOS: dict[str, dict[str, Any]] = {
    "longo01": {"duration": 900, "width": 1920, "height": 1080, "title": "Meditação da manhã"},
    "short01": {"duration": 45, "width": 1080, "height": 1920, "title": "Respire #shorts"},
    "curto_h": {"duration": 120, "width": 1280, "height": 720, "title": "Curto horizontal"},
    "vert_lg": {"duration": 600, "width": 720, "height": 1280, "title": "Vertical longo"},
}


class FakeYtDlp:
    """Simula ``extrair_ytdlp`` contando as chamadas."""

    def __init__(self, videos: dict[str, dict[str, Any]], falhar: set[str] | None = None) -> None:
        self.videos = videos
        self.falhar = falhar or set()
        self.chamadas: list[str] = []

    def __call__(self, url: str, opcoes: dict[str, Any]) -> dict[str, Any]:
        self.chamadas.append(url)
        if "list=" in url:
            assert opcoes.get("extract_flat") == "in_playlist"
            return {"entries": [{"id": v, "title": d["title"]} for v, d in self.videos.items()]}
        vid = url.rsplit("=", 1)[1]
        if vid in self.falhar:
            raise RuntimeError("Video unavailable. This video is private")
        return {
            "id": vid,
            "channel_id": CANAL,
            "channel": "Canal Teste",
            "upload_date": "20260102",
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
            "description": "desc",
            **self.videos[vid],
        }

    def chamadas_video(self) -> list[str]:
        return [c for c in self.chamadas if "watch?v=" in c]


def _sem_rede(video_id: str) -> bool | None:
    raise AssertionError("não deveria consultar /shorts/")


@pytest.mark.parametrize(
    ("dur", "w", "h", "esperado"),
    [
        (900, 1920, 1080, "longo"),
        (45, 1080, 1920, "short"),
        (180, 1080, 1920, "short"),
        (181, 1080, 1920, "longo"),
        (120, 1280, 720, "longo"),
        (60, 1080, 1080, "longo"),
        (400, None, None, "longo"),
        (60, None, None, None),
        (None, 1080, 1920, "longo"),
    ],
)
def test_classificar(dur, w, h, esperado) -> None:
    assert classificar(dur, w, h) == esperado


def test_dimensoes_pelos_formatos() -> None:
    info = {
        "formats": [
            {"width": 360, "height": 640, "vcodec": "avc1"},
            {"width": 1080, "height": 1920, "vcodec": "vp9"},
            {"width": None, "height": None, "vcodec": "none"},
        ]
    }
    assert dimensoes(info) == (1080, 1920)
    assert dimensoes({}) == (None, None)


def test_montar_meta_fallback_url_shorts() -> None:
    m = montar_meta({"id": "abc", "duration": 30}, 1, lambda vid: True)
    assert (m.tipo, m.tipo_origem) == ("short", "url_shorts")
    m = montar_meta({"id": "abc", "duration": 30}, 1, lambda vid: None)
    assert m.tipo == "longo"


def test_montar_meta_campos() -> None:
    info = FakeYtDlp(VIDEOS)("https://www.youtube.com/watch?v=short01", {})
    m = montar_meta(info, 2, _sem_rede)
    assert m.tipo == "short" and m.tipo_origem == "dimensoes"
    assert m.data_publicacao == "2026-01-02"
    assert m.channel_id == CANAL
    assert m.url == "https://www.youtube.com/watch?v=short01"


def test_listar_job_e_idempotencia(tmp_path: Path) -> None:
    fake = FakeYtDlp(VIDEOS)
    with abrir_estado(tmp_path) as estado:
        kw = dict(
            job="j",
            url_playlist=PLAYLIST,
            pasta_saida=tmp_path,
            estado=estado,
            extrair=fake,
            opcoes={},
            verificar_shorts=_sem_rede,
        )
        r = listar_job(**kw)
        tipos = {m.video_id: m.tipo for m in r.todos}
        assert tipos == {
            "longo01": "longo",
            "short01": "short",
            "curto_h": "longo",
            "vert_lg": "longo",
        }
        assert len(r.novos) == 4 and not r.erros
        meta = json.loads((tmp_path / "j" / "short01" / "meta.json").read_text(encoding="utf-8"))
        assert meta["tipo"] == "short" and meta["titulo"] == "Respire #shorts"

        # segunda execução: não consulta metadados de novo e não duplica
        r2 = listar_job(**kw)
        assert len(r2.existentes) == 4 and not r2.novos
        assert len(fake.chamadas_video()) == 4
        assert len(estado.listar("j")) == 4
        assert [r.video_id for r in estado.listar("j", tipo="short")] == ["short01"]

        # --forcar consulta de novo
        listar_job(**kw, forcar=True)
        assert len(fake.chamadas_video()) == 8


def test_listar_job_ids_erro_e_canal(tmp_path: Path) -> None:
    fake = FakeYtDlp(VIDEOS, falhar={"curto_h"})
    with abrir_estado(tmp_path) as estado:
        r = listar_job(
            job="j",
            url_playlist=PLAYLIST,
            pasta_saida=tmp_path,
            estado=estado,
            channel_id_esperado="UC" + "y" * 22,
            ids=["longo01", "curto_h"],
            extrair=fake,
            opcoes={},
            verificar_shorts=_sem_rede,
        )
        assert [m.video_id for m in r.novos] == ["longo01"]
        assert "private" in r.erros["curto_h"]
        assert [m.video_id for m in r.canal_divergente] == ["longo01"]
        reg = estado.obter("j", "curto_h")
        assert reg is not None and reg.erro == "listar" and reg.tentativas == 1


def test_playlist_invalida(tmp_path: Path) -> None:
    def quebra(url: str, opcoes: dict) -> dict:
        raise RuntimeError("The playlist does not exist")

    with abrir_estado(tmp_path) as estado, pytest.raises(ErroPlaylist, match="pública"):
        listar_job(
            job="j",
            url_playlist=PLAYLIST,
            pasta_saida=tmp_path,
            estado=estado,
            extrair=quebra,
            opcoes={},
        )


def test_meta_corrompido_e_refeito(tmp_path: Path) -> None:
    fake = FakeYtDlp({"longo01": VIDEOS["longo01"]})
    (tmp_path / "j" / "longo01").mkdir(parents=True)
    (tmp_path / "j" / "longo01" / "meta.json").write_text("{quebrado", encoding="utf-8")
    with abrir_estado(tmp_path) as estado:
        r = listar_job(
            job="j",
            url_playlist=PLAYLIST,
            pasta_saida=tmp_path,
            estado=estado,
            extrair=fake,
            opcoes={},
            verificar_shorts=_sem_rede,
        )
    assert [m.video_id for m in r.novos] == ["longo01"]


class PlaylistCortada(FakeYtDlp):
    """yt-dlp que lê só os 2 primeiros vídeos, mas informa o total (como no bug do YouTube)."""

    def __call__(self, url: str, opcoes: dict[str, Any]) -> dict[str, Any]:
        info = super().__call__(url, opcoes)
        if "list=" in url:
            info = {"entries": info["entries"][:2], "playlist_count": len(self.videos) + 1}
        return info


def _listar_cortada(tmp_path: Path, estado, completar):  # noqa: ANN001, ANN202
    return listar_job(
        job="j",
        url_playlist=PLAYLIST,
        pasta_saida=tmp_path,
        estado=estado,
        extrair=PlaylistCortada(VIDEOS),
        opcoes={},
        verificar_shorts=_sem_rede,
        completar=completar,
    )


def test_playlist_cortada_completada_pela_api(tmp_path: Path) -> None:
    pedidos: list[str] = []

    def completar(playlist_id: str) -> list[str]:
        pedidos.append(playlist_id)
        return ["vert_lg", "longo01", "short01", "curto_h"]  # ordem da API

    with abrir_estado(tmp_path) as estado:
        r = _listar_cortada(tmp_path, estado, completar)
        assert pedidos == ["PLteste"]
        assert (r.total_informado, r.lidos_ytdlp, r.completada_por) == (5, 2, 2)
        assert r.aviso is None
        assert [m.video_id for m in r.todos] == ["vert_lg", "longo01", "short01", "curto_h"]
        assert len(estado.listar("j")) == 4


def test_playlist_cortada_sem_api(tmp_path: Path) -> None:
    def quebra(playlist_id: str) -> list[str]:
        raise RuntimeError("sem login para o canal")

    with abrir_estado(tmp_path) as estado:
        r = _listar_cortada(tmp_path, estado, None)
        assert len(r.todos) == 2 and "yt-dlp leu só 2" in (r.aviso or "")
        assert "auth" in (r.aviso or "")
        r = _listar_cortada(tmp_path, estado, quebra)
        assert len(r.todos) == 2 and "sem login" in (r.aviso or "")
        r = _listar_cortada(tmp_path, estado, lambda pl: ["longo01", "short01"])
        assert len(r.todos) == 2 and "privado" in (r.aviso or "")


def test_playlist_completa_nao_chama_api(tmp_path: Path) -> None:
    def nao_chamar(playlist_id: str) -> list[str]:
        raise AssertionError("não deveria chamar a API")

    with abrir_estado(tmp_path) as estado:
        r = listar_job(
            job="j",
            url_playlist=PLAYLIST,
            pasta_saida=tmp_path,
            estado=estado,
            extrair=FakeYtDlp(VIDEOS),
            opcoes={},
            verificar_shorts=_sem_rede,
            completar=nao_chamar,
        )
    assert len(r.todos) == 4 and r.aviso is None and not r.completada_por


def test_ids_da_playlist_pagina_e_filtra() -> None:
    from yt_thumbnail.youtube_api import ids_da_playlist

    paginas = {
        None: {
            "items": [
                {"contentDetails": {"videoId": "a"}, "status": {"privacyStatus": "public"}},
                {"contentDetails": {"videoId": "b"}, "status": {"privacyStatus": "private"}},
            ],
            "nextPageToken": "p2",
        },
        "p2": {
            "items": [
                {"contentDetails": {"videoId": "c"}, "status": {"privacyStatus": "unlisted"}},
                {"contentDetails": {}, "status": {"privacyStatus": "privacyStatusUnspecified"}},
                {"contentDetails": {"videoId": "a"}, "status": {"privacyStatus": "public"}},
            ]
        },
    }
    chamadas: list[dict] = []

    class Api:
        def playlistItems(self):  # noqa: N802, ANN202
            return self

        def list(self, **kw):  # noqa: ANN003, ANN202
            chamadas.append(kw)
            self.resp = paginas[kw["pageToken"]]
            return self

        def execute(self):  # noqa: ANN202
            return self.resp

    assert ids_da_playlist(Api(), "PLx") == ["a", "c"]
    assert [c["pageToken"] for c in chamadas] == [None, "p2"]
    assert all(c["playlistId"] == "PLx" and c["maxResults"] == 50 for c in chamadas)
