# SPDX-License-Identifier: GPL-3.0-or-later
"""Backup vertical dos Shorts (restaurar) e proteção do backup no compor."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from test_youtube_api import CANAL, ApiFake
from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.playlist import Meta, gravar_meta, pasta_video
from yt_thumbnail.revisao import (
    ORIGINAL,
    ORIGINAL_VERTICAL,
    ErroRevisao,
    backup_vertical,
    diferenca,
    recorte_central,
)
from yt_thumbnail.youtube_api import restaurar_video


def _quadro(cor: str, largura: int = 1080, altura: int = 1920) -> Image.Image:
    """Um "quadro de vídeo" vertical com alguma forma, para a comparação ter o que ver."""
    img = Image.new("RGB", (largura, altura), cor)
    d = ImageDraw.Draw(img)
    d.ellipse((largura * 0.2, altura * 0.2, largura * 0.8, altura * 0.5), fill="white")
    d.rectangle((0, altura * 0.75, largura, altura), fill="black")
    return img


def _como_o_youtube_serve(quadro: Image.Image, tamanho=(1280, 720)) -> Image.Image:
    """Capa de Short como o YouTube serve: centralizada em 16:9, laterais desfocadas."""
    fundo = quadro.resize(tamanho).filter(ImageFilter.GaussianBlur(30))
    frente = quadro.resize((round(tamanho[1] * quadro.width / quadro.height), tamanho[1]))
    fundo.paste(frente, ((tamanho[0] - frente.width) // 2, 0))
    return fundo


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _short(pasta: Path, backup: Image.Image | None, **meta) -> Meta:
    m = Meta(video_id="s", titulo="s", url="u", tipo="short", listado_em="x", **meta)
    gravar_meta(pasta, m)
    if backup is not None:
        backup.save(pasta / ORIGINAL, "JPEG", quality=92)
    return m


def test_recorte_central_volta_a_capa() -> None:
    quadro = _quadro("navy")
    recorte = recorte_central(_como_o_youtube_serve(quadro), 9 / 16)
    assert recorte.size == (405, 720)
    assert diferenca(recorte, quadro) < 5
    assert diferenca(recorte, _quadro("darkred")) > 12
    # hqdefault (4:3): a capa ocupa a altura inteira
    assert recorte_central(_como_o_youtube_serve(quadro, (480, 360)), 9 / 16).size == (202, 360)


def test_backup_vertical_usa_o_quadro_quando_e_o_mesmo(tmp_path: Path) -> None:
    quadro = _quadro("navy")
    meta = _short(tmp_path, _como_o_youtube_serve(quadro), largura=1080, altura=1920)
    pedidos: list[str] = []

    def baixar(url: str) -> bytes:
        pedidos.append(url)
        return _jpeg(quadro)

    arquivo, origem = backup_vertical(tmp_path, meta, baixar)
    assert arquivo.name == ORIGINAL_VERTICAL and "quadro vertical" in origem
    assert pedidos == ["https://i.ytimg.com/vi/s/oardefault.jpg"]
    assert Image.open(arquivo).size == (1080, 1920)
    # não refaz nem sobrescreve
    de_novo = backup_vertical(tmp_path, meta, lambda url: b"x")
    assert de_novo == (arquivo, "backup vertical já existente")


@pytest.mark.parametrize("falha", ["outro quadro", "404", "horizontal"])
def test_backup_vertical_recorta_quando_o_short_tinha_capa_propria(tmp_path: Path, falha) -> None:
    capa_antiga = _quadro("darkgreen", 720, 900)  # Short 4:5 com capa personalizada
    meta = _short(tmp_path, _como_o_youtube_serve(capa_antiga), largura=720, altura=900)

    def baixar(url: str) -> bytes:
        if falha == "404":
            raise OSError("HTTP Error 404")
        if falha == "horizontal":
            return _jpeg(Image.new("RGB", (120, 90), "gray"))
        return _jpeg(_quadro("darkred", 720, 900).rotate(180))  # outra imagem

    arquivo, origem = backup_vertical(tmp_path, meta, baixar)
    assert "recorte" in origem
    img = Image.open(arquivo)
    assert img.height == 1920 and abs(img.width / img.height - 0.8) < 0.01
    assert diferenca(img, capa_antiga) < 5


def test_backup_vertical_sem_backup_ou_ja_vertical(tmp_path: Path) -> None:
    meta = _short(tmp_path, None)
    with pytest.raises(ErroRevisao, match="revisar"):
        backup_vertical(tmp_path, meta, lambda url: b"")
    _quadro("navy").save(tmp_path / ORIGINAL)
    assert backup_vertical(tmp_path, meta, lambda url: b"") == (
        tmp_path / ORIGINAL,
        "backup já vertical",
    )


def test_restaurar_short_envia_o_backup_vertical(tmp_path: Path) -> None:
    quadro = _quadro("navy")
    pasta = pasta_video(tmp_path, "j", "s")
    _short(pasta, _como_o_youtube_serve(quadro), channel_id=CANAL)
    api = ApiFake()
    with abrir_estado(tmp_path) as estado:
        estado.registrar("j", "s", "enviado", tipo="short")
        restaurar_video(
            api=api,
            estado=estado,
            pasta_saida=tmp_path,
            job="j",
            video_id="s",
            channel_id=CANAL,
            baixar=lambda url: _jpeg(quadro),
        )
        assert estado.obter("j", "s").status == "rejeitado"
    assert api.envios == [("s", ORIGINAL_VERTICAL)]
    envio = json.loads((pasta / "envio.json").read_text("utf-8"))
    assert envio["arquivo"] == ORIGINAL_VERTICAL and "quadro vertical" in envio["origem"]
    assert (pasta / ORIGINAL).is_file()  # o backup original continua lá
