# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de revisao.py e dos comandos revisar/aprovar/rejeitar (sem rede)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageFont
from typer.testing import CliRunner

from yt_thumbnail import cli
from yt_thumbnail.analise.base import Analise, gravar_analise
from yt_thumbnail.cli import app
from yt_thumbnail.composicao import compor_video
from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.playlist import Meta, gravar_meta, pasta_video
from yt_thumbnail.presets import carregar_preset
from yt_thumbnail.revisao import (
    ORIGINAL,
    ErroRevisao,
    aprovar,
    baixar_original,
    pendentes,
    preparar_revisao,
    rejeitar,
    urls_capa,
)

RAIZ = Path(__file__).resolve().parent.parent
runner = CliRunner()


def _imagem(formato: str, tamanho=(1280, 720), cor="#c8b89a") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", tamanho, cor).save(buf, formato)
    return buf.getvalue()


def _meta(vid: str, tipo: str = "longo", thumb: str | None = None) -> Meta:
    return Meta(
        video_id=vid,
        titulo=f"Palestra <{vid}> & cia",
        url=f"https://www.youtube.com/watch?v={vid}",
        tipo=tipo,
        thumbnail_url=thumb,
        listado_em="x",
    )


def _video(saida: Path, estado, job: str, vid: str, tipo: str = "longo") -> Path:
    """Cria um vídeo com 3 capas compostas (fonte embutida do Pillow)."""
    pasta = pasta_video(saida, job, vid)
    gravar_meta(pasta, _meta(vid, tipo))
    gravar_analise(
        pasta,
        Analise(
            tema="tema",
            resumo="Um resumo com <tags> e acentuação.",
            gancho="gancho",
            emocao="paz",
            elementos_visuais=["vela"],
            titulo_capa="Luz que acolhe",
            prompt_imagem="a candle by a window",
            posicao_texto="esquerda",
        ),
        "fake",
        1,
    )
    tamanho = (1280, 720) if tipo == "longo" else (1080, 1920)
    bases = []
    for i in (1, 2, 3):
        Image.new("RGB", tamanho, (200 + i * 10, 190, 170)).save(pasta / f"base_{i}.png")
        bases.append(f"base_{i}.png")
    preset = carregar_preset("espiritualidade", RAIZ / "presets")
    compor_video(
        pasta, bases, "Luz que acolhe", "esquerda", tipo, preset, ImageFont.load_default, "embutida"
    )
    estado.registrar(job, vid, "capas_compostas", tipo=tipo)
    return pasta


# --------------------------------------------------------------------------- capa original


def test_urls_capa_sem_repeticao() -> None:
    urls = urls_capa("abc", "https://i.ytimg.com/vi/abc/maxresdefault.jpg")
    assert urls[0].endswith("maxresdefault.jpg") and len(urls) == len(set(urls)) == 4


def test_baixar_original_pula_placeholder_e_converte(tmp_path: Path) -> None:
    respostas = {
        "https://x/thumb.webp": _imagem("WEBP", (120, 90)),  # "sem capa" do YouTube
        "https://i.ytimg.com/vi/v1/maxresdefault.jpg": _imagem("WEBP"),
    }
    chamadas = []

    def baixar(url: str) -> bytes:
        chamadas.append(url)
        if url not in respostas:
            raise OSError("404")
        return respostas[url]

    url = baixar_original(tmp_path, _meta("v1", thumb="https://x/thumb.webp"), baixar)
    assert url == "https://i.ytimg.com/vi/v1/maxresdefault.jpg"
    with Image.open(tmp_path / ORIGINAL) as img:
        assert img.format == "JPEG" and img.size == (1280, 720)

    # nunca sobrescreve: é o backup
    antes = (tmp_path / ORIGINAL).read_bytes()
    assert baixar_original(tmp_path, _meta("v1"), lambda u: _imagem("JPEG", cor="red")) is None
    assert (tmp_path / ORIGINAL).read_bytes() == antes


def test_baixar_original_falha(tmp_path: Path) -> None:
    def baixar(url: str) -> bytes:
        raise OSError("sem rede")

    with pytest.raises(ErroRevisao, match="sem rede"):
        baixar_original(tmp_path, _meta("v1"), baixar)
    assert not (tmp_path / ORIGINAL).exists()


# --------------------------------------------------------------------------- página


def test_preparar_revisao(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as estado:
        _video(tmp_path, estado, "j", "lg")
        _video(tmp_path, estado, "j", "sh", "short")
        estado.registrar("j", "cedo", "imagens_geradas", tipo="longo")
        aprovar(estado, tmp_path, "j", "sh", 2)
        r = preparar_revisao(
            job="j",
            pasta_saida=tmp_path,
            estado=estado,
            tipos=["longo", "short"],
            baixar=lambda url: _imagem("JPEG"),
        )
        assert sorted(r.originais_baixadas) == ["lg", "sh"]
        assert [i.meta.video_id for i in r.itens] == ["lg", "sh"]  # pendentes primeiro
        assert estado.obter("j", "lg").dados["capa_original_url"].startswith("https://i.ytimg")
        assert estado.obter("j", "lg").status == "capas_compostas"
    pagina = (tmp_path / "j" / "revisao.html").read_text(encoding="utf-8")
    assert r.pagina == tmp_path / "j" / "revisao.html"
    assert "yt-thumbnail aprovar lg --job j --variacao 3" in pagina
    assert "yt-thumbnail rejeitar lg --job j" in pagina
    assert "yt-thumbnail aprovar --job j --todos --variacao 1" in pagina
    assert "lg/capa_1.jpg" in pagina and "lg/mini_1.jpg" in pagina and f"lg/{ORIGINAL}" in pagina
    assert ">SHORT<" in pagina and ">LONGO<" in pagina
    assert "aprovada a variação 2" in pagina
    assert "&lt;lg&gt; &amp; cia" in pagina and "<tags>" not in pagina
    assert "cedo" not in pagina


def test_preparar_revisao_offline(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as estado:
        _video(tmp_path, estado, "j", "lg")
        r = preparar_revisao(
            job="j", pasta_saida=tmp_path, estado=estado, tipos=["longo"], baixar=None
        )
    assert not r.originais_baixadas and not r.itens[0].tem_original
    assert "capa atual não baixada" in r.pagina.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- aprovação


def test_aprovar_e_rejeitar(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as estado:
        _video(tmp_path, estado, "j", "a")
        _video(tmp_path, estado, "j", "b")
        assert pendentes(estado, "j") == ["a", "b"]

        reg = aprovar(estado, tmp_path, "j", "a", 2)
        assert reg.status == "aprovado"
        assert reg.dados["variacao"] == 2 and reg.dados["capa"] == "capa_2.jpg"
        assert pendentes(estado, "j") == ["b"]

        # mudar de ideia antes do envio é permitido
        reg = rejeitar(estado, "j", "a")
        assert reg.status == "rejeitado" and reg.dados["variacao"] is None
        reg = aprovar(estado, tmp_path, "j", "a", 1)
        assert reg.status == "aprovado" and reg.dados["capa"] == "capa_1.jpg"

        with pytest.raises(ErroRevisao, match="variação 4 não existe"):
            aprovar(estado, tmp_path, "j", "b", 4)
        with pytest.raises(ErroRevisao, match="não está no job"):
            aprovar(estado, tmp_path, "j", "zz", 1)

        # depois de enviado, só com --forcar
        estado.registrar("j", "a", "enviado")
        with pytest.raises(ErroRevisao, match="--forcar"):
            rejeitar(estado, "j", "a")
        assert rejeitar(estado, "j", "a", forcar=True).status == "rejeitado"


def test_aprovar_sem_capas(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as estado:
        estado.registrar("j", "x", "imagens_geradas", tipo="longo")
        with pytest.raises(ErroRevisao, match="compor"):
            aprovar(estado, tmp_path, "j", "x", 1)


# --------------------------------------------------------------------------- CLI


def test_cli_revisar_aprovar_rejeitar(projeto: Path, monkeypatch) -> None:
    cfg = str(projeto / "config.yaml")
    saida = projeto / "saida"
    with abrir_estado(saida) as estado:
        for vid in ("v1", "v2", "v3"):
            _video(saida, estado, "meditacoes", vid)
    monkeypatch.setattr(cli, "_baixador_padrao", lambda: lambda url: _imagem("JPEG"))

    r = runner.invoke(app, ["revisar", "-c", cfg, "--nao-abrir"])
    assert r.exit_code == 0, r.output
    assert (saida / "meditacoes" / "revisao.html").is_file()
    assert (pasta_video(saida, "meditacoes", "v1") / ORIGINAL).is_file()

    r = runner.invoke(app, ["aprovar", "v1", "--variacao", "2", "-c", cfg])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["rejeitar", "v2", "-c", cfg])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["aprovar", "--todos", "--variacao", "3", "-c", cfg])
    assert r.exit_code == 0, r.output
    with abrir_estado(saida) as estado:
        assert estado.obter("meditacoes", "v1").dados["variacao"] == 2
        assert estado.obter("meditacoes", "v2").status == "rejeitado"
        assert estado.obter("meditacoes", "v3").dados["variacao"] == 3

    r = runner.invoke(app, ["aprovar", "v1", "--variacao", "9", "-c", cfg])
    assert r.exit_code == 1 and "não existe" in r.output
    r = runner.invoke(app, ["aprovar", "nada", "--variacao", "1", "-c", cfg])
    assert r.exit_code != 0
    r = runner.invoke(app, ["aprovar", "v1", "--todos", "--variacao", "1", "-c", cfg])
    assert r.exit_code != 0
    info = json.loads((pasta_video(saida, "meditacoes", "v1") / "capas.json").read_text("utf-8"))
    assert len(info["capas"]) == 3
