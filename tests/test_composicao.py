# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de composicao.py (fonte embutida do Pillow, sem depender de assets/fonts)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageFont

from yt_thumbnail.analise.base import Analise, gravar_analise
from yt_thumbnail.composicao import (
    LIMITE_BYTES,
    ErroComposicao,
    abrir_fonte_do_preset,
    ajustar_texto,
    compor_capa,
    compor_job,
    contraste,
    ler_capas,
    quebrar,
    regiao_texto,
    salvar_jpeg,
)
from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.playlist import Meta, gravar_meta, pasta_video
from yt_thumbnail.presets import carregar_preset

RAIZ = Path(__file__).resolve().parent.parent


def abrir(tamanho: int):
    return ImageFont.load_default(tamanho)


@pytest.fixture
def preset():
    return carregar_preset("espiritualidade", RAIZ / "presets")


def _gradiente(tamanho: tuple[int, int], claro: bool = True) -> Image.Image:
    w, h = tamanho
    img = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    return img if not claro else Image.eval(img, lambda v: 180 + v // 4)


def test_contraste() -> None:
    assert contraste((0, 0, 0), (255, 255, 255)) == pytest.approx(21, rel=1e-3)
    assert contraste((120, 120, 120), (120, 120, 120)) == pytest.approx(1)


def test_quebrar_equilibra_linhas() -> None:
    fonte = abrir(40)
    linhas = quebrar(["A", "felicidade", "mora", "dentro", "de", "você"], 2, fonte)
    assert len(linhas) == 2
    assert " ".join(linhas) == "A felicidade mora dentro de você"
    larguras = [fonte.getlength(linha) for linha in linhas]
    assert max(larguras) < fonte.getlength("A felicidade mora dentro de você") * 0.7


def test_ajustar_texto_respeita_regiao(preset) -> None:
    regiao = regiao_texto("longo", "esquerda", (1280, 720), preset.layouts.longo)
    tamanho, linhas, coube = ajustar_texto("A mudança começa na raiz", regiao, abrir, 3, 115, 54)
    fonte = abrir(tamanho)
    assert coube and 1 <= len(linhas) <= 3
    assert max(fonte.getlength(linha) for linha in linhas) <= regiao.largura


def test_ajustar_texto_que_nao_cabe(preset) -> None:
    regiao = regiao_texto("longo", "topo", (1280, 720), preset.layouts.longo)
    titulo = " ".join(["palavraenorme"] * 12)
    tamanho, linhas, coube = ajustar_texto(titulo, regiao, abrir, 2, 115, 54)
    assert not coube and tamanho == 54 and len(linhas) == 2


@pytest.mark.parametrize("posicao", ["esquerda", "direita", "topo", "centro"])
def test_regioes_longo(preset, posicao) -> None:
    w, h = 1280, 720
    r = regiao_texto("longo", posicao, (w, h), preset.layouts.longo)
    x0, y0, x1, y1 = preset.layouts.longo.area_segura
    assert x0 * w - 1 <= r.x0 < r.x1 <= x1 * w + 1
    assert y0 * h - 1 <= r.y0 < r.y1 <= y1 * h + 1
    if posicao == "direita":  # não cobre o canto inferior direito (duração do vídeo)
        assert r.y1 <= 0.6 * h


@pytest.mark.parametrize("posicao", ["esquerda", "direita", "topo", "centro"])
def test_regioes_short_no_quadrado_central(preset, posicao) -> None:
    w, h = 1080, 1920
    r = regiao_texto("short", posicao, (w, h), preset.layouts.short)
    assert r.alinhamento == "centro"
    assert r.y0 >= 0.2 * h and r.y1 <= 0.8 * h


def test_cor_automatica(preset) -> None:
    claro = compor_capa(
        Image.new("RGB", (1280, 720), "#F5EFE6"), "Luz", "esquerda", "longo", preset, abrir
    )
    escuro = compor_capa(
        Image.new("RGB", (1280, 720), "#2A2622"), "Luz", "esquerda", "longo", preset, abrir
    )
    assert claro.cor == preset.tipografia.cor_escura
    assert escuro.cor == preset.tipografia.cor_clara
    assert claro.contraste >= 3 and escuro.contraste >= 3


def test_veu_sobe_em_fundo_medio(preset) -> None:
    # cinza médio: nem o texto escuro nem o claro têm contraste 3:1 sem véu
    c = compor_capa(
        Image.new("RGB", (1280, 720), (128, 118, 108)),
        "Paz interior",
        "topo",
        "longo",
        preset,
        abrir,
    )
    assert c.contraste >= 3
    assert c.opacidade_veu >= preset.tipografia.veu.opacidade


def test_titulo_normalizado_nfc(preset) -> None:
    decomposto = "você"  # "você" com acento combinante
    c = compor_capa(_gradiente((1280, 720)), decomposto, "centro", "longo", preset, abrir)
    assert c.linhas == ["você"]


def test_salvar_jpeg_reduz_qualidade(tmp_path: Path) -> None:
    ruido = Image.frombytes("RGB", (1280, 720), os.urandom(1280 * 720 * 3))
    q, n = salvar_jpeg(ruido, tmp_path / "c.jpg", limite=600_000)
    assert n <= 600_000 and q < 90
    with pytest.raises(ErroComposicao):
        salvar_jpeg(ruido, tmp_path / "d.jpg", limite=10_000)


def test_fonte_ausente(preset, tmp_path: Path) -> None:
    with pytest.raises(ErroComposicao, match="baixar_fontes"):
        abrir_fonte_do_preset(preset.tipografia, tmp_path)


def _preparar(tmp_path: Path, estado, videos: dict[str, str]) -> None:
    for vid, tipo in videos.items():
        pasta = pasta_video(tmp_path, "j", vid)
        gravar_meta(pasta, Meta(video_id=vid, titulo=vid, url="u", tipo=tipo, listado_em="x"))
        gravar_analise(
            pasta,
            Analise(
                tema="tema",
                resumo="um resumo qualquer",
                gancho="gancho",
                emocao="paz",
                elementos_visuais=["lamparina"],
                titulo_capa="A luz que acolhe",
                prompt_imagem="a lit oil lamp on a wooden table by an open window",
                posicao_texto="esquerda",
            ),
            "fake",
            1,
        )
        saida = (1280, 720) if tipo == "longo" else (1080, 1920)
        arquivos = []
        for i in (1, 2):
            _gradiente(saida, claro=i == 1).save(pasta / f"base_{i}.png")
            arquivos.append(f"base_{i}.png")
        (pasta / "imagens.json").write_text(
            json.dumps(
                {
                    "modelo": "m",
                    "prompt": "p",
                    "prompt_2": "p",
                    "negative_prompt": "n",
                    "largura": saida[0],
                    "altura": saida[1],
                    "passos": 1,
                    "guidance_scale": 1.0,
                    "seeds": [1, 2],
                    "arquivos": arquivos,
                    "saida": list(saida),
                    "segundos": 1.0,
                    "gerado_em": "x",
                }
            ),
            encoding="utf-8",
        )
        estado.registrar("j", vid, "imagens_geradas", tipo=tipo)


def test_compor_job(tmp_path: Path, preset) -> None:
    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, {"lg": "longo", "sh": "short"})
        estado.registrar("j", "cedo", "analisado", tipo="longo")
        kw = dict(
            job="j",
            tipos=["longo", "short"],
            pasta_saida=tmp_path,
            estado=estado,
            preset=preset,
            abrir=abrir,
            nome_fonte="embutida",
        )
        r = compor_job(**kw)
        assert sorted(r.feitos) == ["lg", "sh"] and not r.erros
        lg = pasta_video(tmp_path, "j", "lg")
        sh = pasta_video(tmp_path, "j", "sh")
        assert Image.open(lg / "capa_1.jpg").size == (1280, 720)
        assert Image.open(lg / "mini_2.jpg").size == (320, 180)
        assert Image.open(sh / "capa_2.jpg").size == (1080, 1920)
        assert Image.open(sh / "mini_1.jpg").size == (180, 320)
        for pasta in (lg, sh):
            for capa in pasta.glob("capa_*.jpg"):
                assert capa.stat().st_size < LIMITE_BYTES
        dados = ler_capas(lg)
        assert dados is not None and dados.titulo == "A luz que acolhe"
        assert [c.base for c in dados.capas] == ["base_1.png", "base_2.png"]
        assert estado.obter("j", "lg").status == "capas_compostas"
        assert estado.obter("j", "cedo").status == "analisado"

        # idempotente
        assert not compor_job(**kw).feitos
        # imagens geradas de novo -> recompõe só esse vídeo
        imagens = lg / "imagens.json"
        futuro = (lg / "capas.json").stat().st_mtime + 10
        os.utime(imagens, (futuro, futuro))
        assert list(compor_job(**kw).feitos) == ["lg"]


def test_compor_job_sem_imagens_registra_erro(tmp_path: Path, preset) -> None:
    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, {"a": "longo"})
        (pasta_video(tmp_path, "j", "a") / "base_2.png").unlink()
        r = compor_job(
            job="j",
            tipos=["longo"],
            pasta_saida=tmp_path,
            estado=estado,
            preset=preset,
            abrir=abrir,
            nome_fonte="embutida",
        )
        assert "a" in r.erros
        assert estado.obter("j", "a").erro == "compor"
