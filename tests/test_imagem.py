# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de imagem.py (gerador simulado, sem GPU)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from yt_thumbnail.analise.base import Analise, gravar_analise
from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.imagem import (
    ParametrosImagem,
    ajustar,
    gerar_job,
    ler_imagens,
    montar_parametros,
)
from yt_thumbnail.playlist import Meta, gravar_meta, pasta_video
from yt_thumbnail.presets import carregar_preset

RAIZ = Path(__file__).resolve().parent.parent
FORMATOS = {"longo": ((1344, 768), (1280, 720)), "short": ((768, 1344), (1080, 1920))}


@pytest.fixture
def preset():
    return carregar_preset("espiritualidade", RAIZ / "presets")


class FakeGerador:
    modelo = "fake-sdxl"

    def __init__(self, falhar: set[int] | None = None) -> None:
        self.chamadas: list[tuple[ParametrosImagem, int]] = []
        self.falhar = falhar or set()

    def gerar(self, p: ParametrosImagem, seed: int) -> Image.Image:
        self.chamadas.append((p, seed))
        if len(self.chamadas) in self.falhar:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        return Image.new("RGB", (p.largura, p.altura), (seed % 256, 200, 180))


def test_montar_parametros(preset) -> None:
    p = montar_parametros("A wooden gate in a wheat field.", preset, "m", (1344, 768))
    assert p.prompt == "A wooden gate in a wheat field"
    assert p.prompt_2.startswith("soft natural light") and p.prompt_2.endswith("wheat field")
    assert "text" in p.negative_prompt
    assert (p.largura, p.altura, p.passos, p.guidance_scale) == (1344, 768, 30, 6.0)


@pytest.mark.parametrize(
    ("origem", "saida"),
    [((1344, 768), (1280, 720)), ((768, 1344), (1080, 1920)), ((1024, 1024), (1280, 720))],
)
def test_ajustar(origem, saida) -> None:
    img = Image.new("RGB", origem, "white")
    assert ajustar(img, saida).size == saida


def test_ajustar_recorta_o_centro() -> None:
    img = Image.new("RGB", (300, 100), "red")
    img.paste(Image.new("RGB", (100, 100), "blue"), (100, 0))
    out = ajustar(img, (100, 100))
    assert out.getpixel((50, 50)) == (0, 0, 255)


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
                titulo_capa="Título curto",
                prompt_imagem="a lit oil lamp on a wooden table by an open window",
                posicao_texto="esquerda",
            ),
            "fake",
            1,
        )
        estado.registrar("j", vid, "analisado", tipo=tipo)


def test_gerar_job(tmp_path: Path, preset) -> None:
    g = FakeGerador()
    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, {"lg": "longo", "sh": "short"})
        estado.registrar("j", "cedo", "transcrito", tipo="longo")
        kw = dict(
            job="j",
            tipos=["longo", "short"],
            pasta_saida=tmp_path,
            estado=estado,
            gerador=g,
            preset=preset,
            formatos=FORMATOS,
            variacoes=3,
        )
        r = gerar_job(**kw)
        assert sorted(r.feitos) == ["lg", "sh"] and not r.erros
        assert len(g.chamadas) == 6
        lg = pasta_video(tmp_path, "j", "lg")
        assert Image.open(lg / "base_1.png").size == (1280, 720)
        sh = pasta_video(tmp_path, "j", "sh")
        assert Image.open(sh / "base_3.png").size == (1080, 1920)
        # gerado na resolução nativa do tipo
        tamanhos = {(p.largura, p.altura) for p, _ in g.chamadas}
        assert tamanhos == {(1344, 768), (768, 1344)}
        info = json.loads((lg / "imagens.json").read_text(encoding="utf-8"))
        assert len(set(info["seeds"])) == 3 and info["arquivos"] == [
            "base_1.png",
            "base_2.png",
            "base_3.png",
        ]
        assert estado.obter("j", "lg").status == "imagens_geradas"
        assert estado.obter("j", "lg").dados["seeds"] == info["seeds"]
        assert estado.obter("j", "cedo").status == "transcrito"

        # idempotente
        r2 = gerar_job(**kw)
        assert not r2.feitos and len(g.chamadas) == 6
        # imagem apagada -> refaz só esse vídeo
        (lg / "base_2.png").unlink()
        assert ler_imagens(lg, 3) is None
        r3 = gerar_job(**kw)
        assert list(r3.feitos) == ["lg"]


def test_erro_de_memoria_nao_derruba_lote(tmp_path: Path, preset) -> None:
    g = FakeGerador(falhar={1})
    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, {"a": "longo", "b": "longo"})
        r = gerar_job(
            job="j",
            tipos=["longo"],
            pasta_saida=tmp_path,
            estado=estado,
            gerador=g,
            preset=preset,
            formatos=FORMATOS,
            variacoes=1,
        )
        assert list(r.feitos) == ["b"]
        assert "attention_slicing" in r.erros["a"]
        assert estado.obter("j", "a").erro == "gerar"


def test_compatibilidade_vae_tiling() -> None:
    from yt_thumbnail.imagem import _ativar_attention_slicing, _ativar_vae_tiling

    class Vae:
        ativo = False

        def enable_tiling(self) -> None:
            self.ativo = True

    class PipeNovo:  # diffusers >= 0.4x: só pipe.vae.enable_tiling
        vae = Vae()

    class PipeAntigo:
        vae = None
        chamado = False

        def enable_vae_tiling(self) -> None:
            self.chamado = True

    novo, antigo = PipeNovo(), PipeAntigo()
    _ativar_vae_tiling(novo)
    _ativar_vae_tiling(antigo)
    assert novo.vae.ativo and antigo.chamado

    class Unet:
        fatia = None

        def set_attention_slice(self, v: str) -> None:
            self.fatia = v

    class SoUnet:
        unet = Unet()

    p = SoUnet()
    _ativar_attention_slicing(p)
    assert p.unet.fatia == "auto"
