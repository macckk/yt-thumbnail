# SPDX-License-Identifier: GPL-3.0-or-later
"""Interface dos backends de análise e o fluxo comum (prompt, validação, novas tentativas).

Entrada: ``meta.json`` + ``transcricao.txt`` + preset. Saída: ``analise.json``.
Um backend só precisa implementar :meth:`BackendAnalise.gerar` (texto do prompt → JSON).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from yt_thumbnail.estado import ORDEM, Estado
from yt_thumbnail.playlist import Meta, ler_meta, pasta_video
from yt_thumbnail.presets import Preset
from yt_thumbnail.transcricao import ler_info

PosicaoTexto = Literal["esquerda", "direita", "topo", "centro"]


class ErroAnalise(Exception):
    """A análise falhou (resposta inválida depois de todas as tentativas, backend indisponível)."""


class ErroBackend(ErroAnalise):
    """O backend não pôde ser executado (não instalado, sem login, tempo esgotado)."""


class Analise(BaseModel):
    """Resposta esperada do backend (esquema de ``analise.json``)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    tema: str = Field(min_length=2)
    resumo: str = Field(min_length=10)
    gancho: str = Field(min_length=2)
    emocao: str = Field(min_length=2)
    elementos_visuais: list[str] = Field(min_length=1)
    titulo_capa: str = Field(min_length=2)
    prompt_imagem: str = Field(min_length=20)
    posicao_texto: PosicaoTexto

    @field_validator("posicao_texto", mode="before")
    @classmethod
    def _posicao(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("titulo_capa")
    @classmethod
    def _titulo(cls, v: str) -> str:
        return v.strip().strip("\"'“”").strip()


def esquema_json() -> dict[str, Any]:
    """JSON Schema da resposta (para backends com saída estruturada)."""
    return {
        "type": "object",
        "properties": {
            "tema": {"type": "string"},
            "resumo": {"type": "string"},
            "gancho": {"type": "string"},
            "emocao": {"type": "string"},
            "elementos_visuais": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "titulo_capa": {"type": "string"},
            "prompt_imagem": {"type": "string"},
            "posicao_texto": {"type": "string", "enum": ["esquerda", "direita", "topo", "centro"]},
        },
        "required": [
            "tema",
            "resumo",
            "gancho",
            "emocao",
            "elementos_visuais",
            "titulo_capa",
            "prompt_imagem",
            "posicao_texto",
        ],
        "additionalProperties": False,
    }


class BackendAnalise(Protocol):
    """Um backend recebe o prompt completo e devolve o texto da resposta (JSON)."""

    nome: str

    def gerar(self, prompt: str, esquema: dict[str, Any]) -> str:
        """Devolve a resposta do modelo (idealmente só o objeto JSON).

        Raises:
            ErroBackend: se o backend não puder ser executado.
        """
        ...


class ArquivoAnalise(Analise):
    """Conteúdo de ``analise.json``: a análise + metadados da execução."""

    backend: str
    tentativas: int
    analisado_em: str


@dataclass
class ResultadoAnalise:
    """Resumo de :func:`analisar_job`."""

    feitos: dict[str, ArquivoAnalise] = field(default_factory=dict)
    existentes: list[str] = field(default_factory=list)
    erros: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- prompt


def truncar_transcricao(texto: str, limite: int) -> str:
    """Reduz a transcrição a ~``limite`` caracteres mantendo início, meio e fim.

    Palestras longas costumam ter a introdução no começo e a mensagem central no meio/fim;
    três blocos preservam melhor o tema do que cortar só o final.
    """
    if len(texto) <= limite:
        return texto
    marca = "\n[...]\n"
    bloco = (limite - 2 * len(marca)) // 3
    meio = len(texto) // 2
    partes = [texto[:bloco], texto[meio - bloco // 2 : meio + bloco - bloco // 2], texto[-bloco:]]
    return marca.join(p.strip() for p in partes)


def preencher(template: str, valores: dict[str, Any]) -> str:
    """Substitui ``{chave}`` só para as chaves conhecidas (o JSON de exemplo fica intacto)."""
    padrao = re.compile(r"\{(" + "|".join(map(re.escape, valores)) + r")\}")
    return padrao.sub(lambda m: str(valores[m.group(1)]), template)


def montar_prompt(
    template: str, meta: Meta, transcricao: str, preset: Preset, limite_caracteres: int
) -> str:
    """Monta o prompt a partir do template ``prompts/analise.md`` e do preset."""
    texto = transcricao.strip()
    if not texto:
        texto = "(vídeo sem fala transcrita: baseie-se no título e na descrição)"
    else:
        texto = truncar_transcricao(texto, limite_caracteres)
    a = preset.analise
    return preencher(
        template,
        {
            "tipo": meta.tipo,
            "titulo": meta.titulo,
            "descricao": (meta.descricao or "(sem descrição)")[:2000],
            "transcricao": texto,
            "preset": preset.nome,
            "tom": a.tom,
            "titulo_min": a.titulo_palavras[0],
            "titulo_max": a.titulo_palavras[1],
            "proibido": "; ".join(a.proibido) or "nada específico",
            "diretrizes_imagem": a.diretrizes_imagem or "livre",
            "simbolos": preset.imagem.simbolos,
        },
    )


# --------------------------------------------------------------------------- resposta


def extrair_json(texto: str) -> dict[str, Any]:
    """Extrai o primeiro objeto JSON da resposta (aceita bloco ```json ... ``` ou texto em volta).

    Raises:
        ValueError: se não houver JSON válido.
    """
    texto = texto.strip()
    cerca = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.S)
    if cerca:
        texto = cerca.group(1)
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio < 0 or fim <= inicio:
            raise ValueError("a resposta não contém um objeto JSON") from None
        dados = json.loads(texto[inicio : fim + 1])
    if not isinstance(dados, dict):
        raise ValueError("a resposta JSON não é um objeto")
    return dados


def validar(dados: dict[str, Any], preset: Preset) -> Analise:
    """Valida o esquema e as regras do preset (tamanho do título).

    Raises:
        ValueError: com a lista de problemas, para ser devolvida ao modelo na nova tentativa.
    """
    try:
        analise = Analise.model_validate(dados)
    except ValidationError as e:
        problemas = "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
        )
        raise ValueError(problemas) from e
    minimo, maximo = preset.analise.titulo_palavras
    n = len(analise.titulo_capa.split())
    if not minimo <= n <= maximo:
        raise ValueError(f"titulo_capa tem {n} palavra(s); deve ter entre {minimo} e {maximo}")
    return analise


def analisar_texto(
    backend: BackendAnalise, prompt: str, preset: Preset, tentativas_extras: int
) -> tuple[Analise, int]:
    """Chama o backend e valida; em caso de resposta inválida, tenta de novo explicando o erro.

    Returns:
        A análise e o número de chamadas feitas.

    Raises:
        ErroAnalise: se todas as tentativas falharem.
        ErroBackend: se o backend não puder ser executado (não adianta tentar de novo).
    """
    esquema = esquema_json()
    prompt_atual = prompt
    ultimo_erro = ""
    for tentativa in range(1, tentativas_extras + 2):
        resposta = backend.gerar(prompt_atual, esquema)
        try:
            return validar(extrair_json(resposta), preset), tentativa
        except (ValueError, json.JSONDecodeError) as e:
            ultimo_erro = str(e)
            prompt_atual = (
                f"{prompt}\n\n## Correção\nSua resposta anterior foi rejeitada: {ultimo_erro}.\n"
                "Responda novamente apenas com o objeto JSON válido, corrigindo esse problema."
            )
    raise ErroAnalise(f"resposta inválida após {tentativas_extras + 1} tentativa(s): {ultimo_erro}")


# --------------------------------------------------------------------------- arquivos


def ler_analise(pasta: Path) -> ArquivoAnalise | None:
    """Lê ``analise.json``; ``None`` se não existir ou estiver inválido."""
    arquivo = pasta / "analise.json"
    if not arquivo.is_file():
        return None
    try:
        return ArquivoAnalise.model_validate_json(arquivo.read_text(encoding="utf-8"))
    except (ValidationError, ValueError):
        return None


def gravar_analise(pasta: Path, analise: Analise, backend: str, tentativas: int) -> ArquivoAnalise:
    """Grava ``analise.json`` (escrita atômica)."""
    arquivo = ArquivoAnalise(
        **analise.model_dump(),
        backend=backend,
        tentativas=tentativas,
        analisado_em=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    destino = pasta / "analise.json"
    temp = destino.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(arquivo.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(destino)
    return arquivo


# --------------------------------------------------------------------------- job


def analisar_job(
    *,
    job: str,
    tipos: Iterable[str],
    pasta_saida: Path,
    estado: Estado,
    backend: BackendAnalise,
    preset: Preset,
    template: str,
    limite_caracteres: int = 20000,
    tentativas_extras: int = 2,
    ids: Iterable[str] | None = None,
    forcar: bool = False,
    limite: int | None = None,
    ao_progredir: Callable[[str, int, int], None] | None = None,
) -> ResultadoAnalise:
    """Analisa os vídeos transcritos do job; idempotente (pula quem já tem ``analise.json``).

    Um :class:`ErroBackend` (ex.: Claude Code sem login) interrompe o lote, porque afetaria
    todos os vídeos; os demais erros ficam registrados no estado do vídeo.
    """
    tipos = set(tipos)
    filtro = set(ids) if ids else None
    resultado = ResultadoAnalise()
    pendentes = []
    for r in estado.listar(job):
        if r.tipo not in tipos or (filtro is not None and r.video_id not in filtro):
            continue
        if ORDEM[r.status] < ORDEM["transcrito"]:
            continue
        pasta = pasta_video(pasta_saida, job, r.video_id)
        if not forcar and ler_analise(pasta) is not None:
            resultado.existentes.append(r.video_id)
            if ORDEM[r.status] < ORDEM["analisado"]:
                estado.registrar(job, r.video_id, "analisado")
            continue
        pendentes.append(r)
    if limite is not None:
        pendentes = pendentes[:limite]
    for i, r in enumerate(pendentes, start=1):
        if ao_progredir:
            ao_progredir(r.video_id, i, len(pendentes))
        pasta = pasta_video(pasta_saida, job, r.video_id)
        meta = ler_meta(pasta)
        info = ler_info(pasta)
        if meta is None or info is None:
            msg = "meta.json ou transcricao.json ausente; rode `listar` e `transcrever` antes"
            estado.marcar_erro(job, r.video_id, "analisar", msg)
            resultado.erros[r.video_id] = msg
            continue
        transcricao = (pasta / "transcricao.txt").read_text(encoding="utf-8")
        prompt = montar_prompt(template, meta, transcricao, preset, limite_caracteres)
        try:
            analise, n = analisar_texto(backend, prompt, preset, tentativas_extras)
        except ErroBackend:
            raise
        except ErroAnalise as e:
            estado.marcar_erro(job, r.video_id, "analisar", str(e))
            resultado.erros[r.video_id] = str(e)
            continue
        arquivo = gravar_analise(pasta, analise, backend.nome, n)
        estado.registrar(
            job,
            r.video_id,
            "analisado",
            dados={"titulo_capa": analise.titulo_capa},
            permitir_regredir=forcar,
        )
        resultado.feitos[r.video_id] = arquivo
    return resultado
