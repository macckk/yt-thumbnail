# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes de youtube_api.py e dos comandos auth/canais/enviar/restaurar (API simulada)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from yt_thumbnail import cli
from yt_thumbnail.cli import app
from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.playlist import Meta, gravar_meta, pasta_video
from yt_thumbnail.revisao import ORIGINAL
from yt_thumbnail.youtube_api import (
    Canal,
    ErroYouTube,
    classificar_erro_http,
    enviar_job,
    gravar_channel_id_no_config,
    restaurar_video,
)

CANAL = "UC" + "a" * 22
OUTRO = "UC" + "b" * 22
runner = CliRunner()


class Resp:
    def __init__(self, status: int) -> None:
        self.status = status


class HttpErroFake(Exception):
    """Imita googleapiclient.errors.HttpError (resp.status + content JSON)."""

    def __init__(self, status: int, motivo: str = "", mensagem: str = "erro") -> None:
        super().__init__(mensagem)
        self.resp = Resp(status)
        self.content = json.dumps(
            {"error": {"message": mensagem, "errors": [{"reason": motivo}]}}
        ).encode()


class ApiFake:
    def __init__(self, falhas: dict[str, list[Exception]] | None = None) -> None:
        self.envios: list[tuple[str, str]] = []
        self.falhas = falhas or {}

    def enviar_capa(self, video_id: str, arquivo: Path) -> dict:
        fila = self.falhas.get(video_id) or []
        if fila:
            raise fila.pop(0)
        self.envios.append((video_id, arquivo.name))
        return {"items": [{"default": {"url": f"https://i.ytimg.com/vi/{video_id}/x.jpg"}}]}

    def canal_do_video(self, video_id: str) -> str | None:
        return CANAL


def _video(
    saida: Path,
    estado,
    vid: str,
    *,
    tipo: str = "longo",
    canal: str | None = CANAL,
    backup: bool = True,
    status: str = "aprovado",
    job: str = "j",
) -> Path:
    pasta = pasta_video(saida, job, vid)
    gravar_meta(
        pasta,
        Meta(video_id=vid, titulo=vid, url="u", tipo=tipo, channel_id=canal, listado_em="x"),
    )
    Image.new("RGB", (64, 36), "white").save(pasta / "capa_2.jpg")
    if backup:
        Image.new("RGB", (64, 36), "blue").save(pasta / ORIGINAL)
    estado.registrar(job, vid, "capas_compostas", tipo=tipo)
    if status == "aprovado":
        estado.registrar(job, vid, "aprovado", dados={"variacao": 2, "capa": "capa_2.jpg"})
    return pasta


def _kw(tmp_path: Path, estado, api, **extra):
    kw = dict(
        job="j",
        tipos=["longo", "short"],
        pasta_saida=tmp_path,
        estado=estado,
        channel_id=CANAL,
        shorts_capa_personalizada=False,
        api=api,
        dormir=lambda s: None,
    )
    kw.update(extra)
    return kw


def test_enviar_regras(tmp_path: Path) -> None:
    api = ApiFake()
    with abrir_estado(tmp_path) as estado:
        _video(tmp_path, estado, "ok")
        _video(tmp_path, estado, "short", tipo="short")
        _video(tmp_path, estado, "outro", canal=OUTRO)
        _video(tmp_path, estado, "sembackup", backup=False)
        _video(tmp_path, estado, "pendente", status="capas_compostas")

        simulado = enviar_job(**_kw(tmp_path, estado, None, dry_run=True))
        assert simulado.simulados == ["ok"] and not api.envios
        assert estado.obter("j", "short").status == "aprovado"  # dry-run não muda nada

        r = enviar_job(**_kw(tmp_path, estado, api))
        assert r.enviados == ["ok"] and api.envios == [("ok", "capa_2.jpg")]
        assert list(r.nao_elegiveis) == ["short"]
        assert set(r.pulados) == {"outro", "sembackup"}
        assert estado.obter("j", "ok").status == "enviado"
        assert estado.obter("j", "short").status == "nao_elegivel"
        assert estado.obter("j", "pendente").status == "capas_compostas"
        envio = json.loads((pasta_video(tmp_path, "j", "ok") / "envio.json").read_text("utf-8"))
        assert envio["variacao"] == 2 and envio["channel_id"] == CANAL
        assert len(envio["historico"]) == 1

        # reexecutar não reenvia
        assert not enviar_job(**_kw(tmp_path, estado, api)).enviados


def test_short_em_canal_com_capa_propria(tmp_path: Path) -> None:
    api = ApiFake({"s2": [HttpErroFake(403, "forbidden", "não pode")]})
    with abrir_estado(tmp_path) as estado:
        _video(tmp_path, estado, "s1", tipo="short")
        _video(tmp_path, estado, "s2", tipo="short")
        r = enviar_job(**_kw(tmp_path, estado, api, shorts_capa_personalizada=True))
        assert r.enviados == ["s1"]
        assert r.nao_elegiveis == {"s2": "não pode"}
        assert estado.obter("j", "s2").status == "nao_elegivel"


def test_backoff_cota_e_erro(tmp_path: Path) -> None:
    esperas: list[float] = []
    api = ApiFake(
        {
            "a": [HttpErroFake(429, "rateLimitExceeded"), HttpErroFake(503)],
            "b": [HttpErroFake(400, "invalidImage", "imagem inválida")],
            "c": [HttpErroFake(403, "quotaExceeded", "cota")],
        }
    )
    with abrir_estado(tmp_path) as estado:
        for vid in ("a", "b", "c", "d"):
            _video(tmp_path, estado, vid)
        r = enviar_job(**_kw(tmp_path, estado, api, dormir=esperas.append, pausa=(1.0, 1.0)))
    assert r.enviados == ["a"]  # depois de 2 retentativas
    assert esperas[:2] == [30.0, 60.0]
    assert "imagem inválida" in r.erros["b"]
    assert r.parado_por and "cota" in r.parado_por  # para o lote: "d" nem é tentado
    assert [v for v, _ in api.envios] == ["a"]


def test_sem_channel_id(tmp_path: Path) -> None:
    with abrir_estado(tmp_path) as estado, pytest.raises(ErroYouTube, match="auth"):
        enviar_job(**_kw(tmp_path, estado, ApiFake(), channel_id=None))


def test_restaurar(tmp_path: Path) -> None:
    api = ApiFake()
    with abrir_estado(tmp_path) as estado:
        _video(tmp_path, estado, "v")
        enviar_job(**_kw(tmp_path, estado, api))
        restaurar_video(
            api=api, estado=estado, pasta_saida=tmp_path, job="j", video_id="v", channel_id=CANAL
        )
        assert api.envios[-1] == ("v", ORIGINAL)
        reg = estado.obter("j", "v")
        assert reg.status == "rejeitado" and reg.dados["restaurado_em"]
        envio = json.loads((pasta_video(tmp_path, "j", "v") / "envio.json").read_text("utf-8"))
        assert envio["acao"] == "restaurar" and len(envio["historico"]) == 2

        _video(tmp_path, estado, "x", backup=False)
        with pytest.raises(ErroYouTube, match="backup"):
            restaurar_video(
                api=api,
                estado=estado,
                pasta_saida=tmp_path,
                job="j",
                video_id="x",
                channel_id=CANAL,
            )
        _video(tmp_path, estado, "y", canal=OUTRO)
        with pytest.raises(ErroYouTube, match="canal"):
            restaurar_video(
                api=api,
                estado=estado,
                pasta_saida=tmp_path,
                job="j",
                video_id="y",
                channel_id=CANAL,
            )


def test_classificar_erro_http() -> None:
    assert classificar_erro_http(HttpErroFake(403, "quotaExceeded", "cota")) == (
        403,
        "quotaExceeded",
        "cota",
    )
    assert classificar_erro_http(ValueError("x")) == (None, "", "x")


def test_gravar_channel_id_no_config(tmp_path: Path, raiz: Path) -> None:
    arquivo = tmp_path / "config.yaml"
    shutil.copy(raiz / "config.example.yaml", arquivo)
    assert gravar_channel_id_no_config(arquivo, "espiritual-principal", CANAL)
    assert f"channel_id: {CANAL}" in arquivo.read_text(encoding="utf-8")
    assert not gravar_channel_id_no_config(arquivo, "espiritual-principal", OUTRO)  # já tem
    assert not gravar_channel_id_no_config(arquivo, "nao-existe", OUTRO)


# --------------------------------------------------------------------------- CLI


def test_cli_auth_preenche_channel_id(projeto: Path, monkeypatch) -> None:
    cfg = projeto / "config.yaml"

    class Cred:
        def to_json(self) -> str:
            return '{"token": "t"}'

    monkeypatch.setattr(cli, "_autenticar", lambda c, abrir: (Cred(), Canal(CANAL, "Meu canal")))
    r = runner.invoke(app, ["auth", "--canal", "espiritual-principal", "-c", str(cfg)])
    assert r.exit_code == 0, r.output
    assert (projeto / "secrets" / "tokens" / f"{CANAL}.json").is_file()
    assert f"channel_id: {CANAL}" in cfg.read_text(encoding="utf-8")

    # canal diferente do configurado: recusa
    monkeypatch.setattr(cli, "_autenticar", lambda c, abrir: (Cred(), Canal(OUTRO, "Outro")))
    r = runner.invoke(app, ["auth", "--canal", "espiritual-principal", "-c", str(cfg)])
    assert r.exit_code == 1 and OUTRO in r.output
    assert not (projeto / "secrets" / "tokens" / f"{OUTRO}.json").exists()

    r = runner.invoke(app, ["auth", "--canal", "nao-existe", "-c", str(cfg)])
    assert r.exit_code != 0


def test_cli_canais_sem_login(projeto: Path) -> None:
    r = runner.invoke(app, ["canais", "-c", str(projeto / "config.yaml")])
    assert r.exit_code == 1 and "falta" in r.output


def test_cli_enviar_dry_run_e_real(projeto: Path, monkeypatch) -> None:
    cfg = projeto / "config.yaml"
    gravar_channel_id_no_config(cfg, "espiritual-principal", CANAL)
    saida = projeto / "saida"
    with abrir_estado(saida) as estado:
        _video(saida, estado, "v1", job="meditacoes")
    api = ApiFake()
    monkeypatch.setattr(cli, "_api_do_canal", lambda c, ch: api)

    r = runner.invoke(app, ["enviar", "-c", str(cfg)])
    assert r.exit_code != 0  # exige --aprovados
    r = runner.invoke(app, ["enviar", "--aprovados", "--dry-run", "-c", str(cfg)])
    assert r.exit_code == 0, r.output
    assert "enviaria v1: variação 2" in r.output and not api.envios

    monkeypatch.setattr("yt_thumbnail.youtube_api.time.sleep", lambda s: None)
    r = runner.invoke(app, ["enviar", "--aprovados", "-c", str(cfg)])
    assert r.exit_code == 0, r.output
    assert api.envios == [("v1", "capa_2.jpg")]

    r = runner.invoke(app, ["restaurar", "v1", "-c", str(cfg)])
    assert r.exit_code == 0, r.output
    assert api.envios[-1] == ("v1", ORIGINAL)
