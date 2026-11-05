# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da análise (backend simulado; Claude Code com subprocess simulado)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from yt_thumbnail.analise import criar_backend
from yt_thumbnail.analise.base import (
    ErroBackend,
    analisar_job,
    extrair_json,
    ler_analise,
    montar_prompt,
    preencher,
    truncar_transcricao,
)
from yt_thumbnail.analise.claude_code import ClaudeCodeBackend, interpretar_saida
from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.playlist import Meta, gravar_meta, pasta_video
from yt_thumbnail.presets import carregar_preset
from yt_thumbnail.transcricao import gravar_transcricao

RAIZ = Path(__file__).resolve().parent.parent
TEMPLATE = (RAIZ / "prompts" / "analise.md").read_text(encoding="utf-8")

BOA = {
    "tema": "perdão",
    "resumo": "A palestra fala sobre perdoar para encontrar paz interior.",
    "gancho": "perdoar liberta quem perdoa",
    "emocao": "paz",
    "elementos_visuais": ["amanhecer", "lago calmo"],
    "titulo_capa": "O perdão liberta",
    "prompt_imagem": "a calm lake at sunrise with soft mist, a person seen from behind "
    "on a wooden pier, warm golden light, wide empty sky on the left",
    "posicao_texto": "Esquerda",
}


@pytest.fixture
def preset():
    return carregar_preset("espiritualidade", RAIZ / "presets")


class FakeBackend:
    nome = "fake"

    def __init__(self, respostas: list[str]) -> None:
        self.respostas = list(respostas)
        self.prompts: list[str] = []

    def gerar(self, prompt: str, esquema: dict[str, Any]) -> str:
        assert "titulo_capa" in esquema["required"]
        self.prompts.append(prompt)
        return self.respostas.pop(0)


def _meta(vid: str = "v1", tipo: str = "longo") -> Meta:
    return Meta(
        video_id=vid,
        titulo="Palestra sobre o perdão",
        descricao="Reflexão espírita",
        url="u",
        tipo=tipo,
        listado_em="x",
    )


def test_preencher_preserva_json() -> None:
    t = 'Tipo {tipo}\n```json\n{\n  "tema": "..."\n}\n```\n{desconhecida}'
    assert preencher(t, {"tipo": "short"}) == (
        'Tipo short\n```json\n{\n  "tema": "..."\n}\n```\n{desconhecida}'
    )


def test_truncar() -> None:
    texto = "A" * 5000 + "M" * 5000 + "Z" * 5000
    curto = truncar_transcricao(texto, 3000)
    assert len(curto) <= 3000
    assert curto.startswith("A") and curto.endswith("Z") and "M" in curto
    assert curto.count("[...]") == 2
    assert truncar_transcricao("abc", 3000) == "abc"


def test_montar_prompt(preset) -> None:
    p = montar_prompt(TEMPLATE, _meta(tipo="short"), "", preset, 20000)
    assert "Tipo: short" in p
    assert "sem fala" in p
    assert "entre 2 e 5 palavras" in p
    assert "promessas milagrosas" in p
    assert "{transcricao}" not in p and '"titulo_capa"' in p


def test_extrair_json() -> None:
    assert extrair_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extrair_json('Claro! {"a": {"b": 2}} Espero ter ajudado.') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        extrair_json("sem json aqui")


def _preparar(tmp_path: Path, estado, videos: dict[str, str], status="transcrito") -> None:
    for vid, texto in videos.items():
        pasta = pasta_video(tmp_path, "j", vid)
        gravar_meta(pasta, _meta(vid))
        gravar_transcricao(pasta, texto, "legenda_auto" if texto else "sem_fala", "pt")
        estado.registrar("j", vid, status, tipo="longo")


def test_analisar_job_tentativas_e_idempotencia(tmp_path: Path, preset) -> None:
    titulo_longo = {**BOA, "titulo_capa": "Um título comprido demais para caber na capa"}
    backend = FakeBackend(
        [
            "não sei responder",  # v1: inválido
            json.dumps(titulo_longo),  # v1: título longo demais
            json.dumps(BOA),  # v1: ok na 3ª
            "```json\n" + json.dumps(BOA) + "\n```",  # v2: ok
        ]
    )
    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, {"v1": "fala sobre perdão " * 50, "v2": ""})
        estado.registrar("j", "v3", "listado", tipo="longo")  # ainda não transcrito
        kw = dict(
            job="j",
            tipos=["longo"],
            pasta_saida=tmp_path,
            estado=estado,
            backend=backend,
            preset=preset,
            template=TEMPLATE,
        )
        r = analisar_job(**kw)
        assert list(r.feitos) == ["v1", "v2"] and not r.erros
        a = ler_analise(pasta_video(tmp_path, "j", "v1"))
        assert a is not None and a.tentativas == 3 and a.posicao_texto == "esquerda"
        assert a.backend == "fake"
        assert "palavra(s); deve ter entre 2 e 5" in backend.prompts[2]
        assert estado.obter("j", "v1").status == "analisado"
        assert estado.obter("j", "v1").dados["titulo_capa"] == "O perdão liberta"
        assert estado.obter("j", "v3").status == "listado"
        # 2ª execução não chama o backend
        r2 = analisar_job(**kw)
        assert not r2.feitos and sorted(r2.existentes) == ["v1", "v2"]


def test_analisar_esgota_tentativas(tmp_path: Path, preset) -> None:
    backend = FakeBackend(["x", "y", "z"])
    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, {"v1": "texto"})
        r = analisar_job(
            job="j",
            tipos=["longo"],
            pasta_saida=tmp_path,
            estado=estado,
            backend=backend,
            preset=preset,
            template=TEMPLATE,
            tentativas_extras=2,
        )
        assert "3 tentativa(s)" in r.erros["v1"]
        reg = estado.obter("j", "v1")
        assert reg.status == "transcrito" and reg.erro == "analisar"


def test_erro_de_backend_interrompe(tmp_path: Path, preset) -> None:
    class SemLogin:
        nome = "x"

        def gerar(self, prompt: str, esquema: dict) -> str:
            raise ErroBackend("sem login")

    with abrir_estado(tmp_path) as estado:
        _preparar(tmp_path, estado, {"v1": "texto"})
        with pytest.raises(ErroBackend):
            analisar_job(
                job="j",
                tipos=["longo"],
                pasta_saida=tmp_path,
                estado=estado,
                backend=SemLogin(),
                preset=preset,
                template=TEMPLATE,
            )


# --------------------------------------------------------------------------- claude -p


def test_interpretar_saida() -> None:
    ok = json.dumps({"type": "result", "is_error": False, "result": json.dumps(BOA)})
    assert json.loads(interpretar_saida(ok, "", 0))["tema"] == "perdão"
    estruturado = json.dumps({"is_error": False, "result": "", "structured_output": BOA})
    assert json.loads(interpretar_saida(estruturado, "", 0))["emocao"] == "paz"
    eventos = json.dumps([{"type": "system"}, {"type": "result", "result": "{}"}])
    assert interpretar_saida(eventos, "", 0) == "{}"
    sem_login = json.dumps({"is_error": True, "result": "Not logged in · Please run /login"})
    with pytest.raises(ErroBackend, match="CLAUDE_CODE_OAUTH_TOKEN"):
        interpretar_saida(sem_login, "", 1)
    with pytest.raises(ErroBackend, match="falhou"):
        interpretar_saida("", "boom", 1)


def test_claude_code_backend(monkeypatch) -> None:
    chamadas: list[dict[str, Any]] = []

    def fake_run(cmd, **kw):
        chamadas.append({"cmd": cmd, **kw})
        saida = json.dumps({"is_error": False, "result": json.dumps(BOA)})
        return subprocess.CompletedProcess(cmd, 0, saida, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    b = ClaudeCodeBackend(modelo="sonnet", executavel="claude")
    resposta = b.gerar("PROMPT", {"type": "object", "required": ["titulo_capa"]})
    assert json.loads(resposta)["titulo_capa"] == "O perdão liberta"
    c = chamadas[0]
    assert c["input"] == "PROMPT"
    assert c["cmd"][:4] == ["claude", "-p", "--output-format", "json"]
    assert "--json-schema" in c["cmd"] and c["cmd"][-2:] == ["--model", "sonnet"]
    assert c["cmd"][c["cmd"].index("--tools") + 1] == ""
    sem_esquema = ClaudeCodeBackend(executavel="claude", saida_estruturada=False).comando({})
    assert "--json-schema" not in sem_esquema


def test_claude_ausente(monkeypatch) -> None:
    import shutil

    monkeypatch.setattr(shutil, "which", lambda nome: None)
    with pytest.raises(ErroBackend, match="não encontrado"):
        ClaudeCodeBackend().comando({})
    with pytest.raises(ErroBackend, match="desconhecido"):
        criar_backend("ollama")
