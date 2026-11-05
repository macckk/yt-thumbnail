# SPDX-License-Identifier: GPL-3.0-or-later
"""Estado por vídeo, persistido em SQLite (``<saida>/estado.db``).

Fluxo de status (ver ``docs/arquitetura.md``)::

    listado → transcrito → analisado → imagens_geradas → capas_compostas → aprovado → enviado
                                                                          ↘ rejeitado
                                                         aprovado → nao_elegivel

Erros não mudam o status: ficam em ``erro``/``mensagem``/``tentativas`` até a etapa dar certo.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal[
    "listado",
    "transcrito",
    "analisado",
    "imagens_geradas",
    "capas_compostas",
    "aprovado",
    "rejeitado",
    "enviado",
    "nao_elegivel",
]

ORDEM: dict[str, int] = {
    "listado": 0,
    "transcrito": 1,
    "analisado": 2,
    "imagens_geradas": 3,
    "capas_compostas": 4,
    "aprovado": 5,
    "rejeitado": 5,
    "enviado": 6,
    "nao_elegivel": 6,
}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS videos (
    job           TEXT NOT NULL,
    video_id      TEXT NOT NULL,
    tipo          TEXT,
    status        TEXT NOT NULL,
    titulo        TEXT,
    erro          TEXT,
    mensagem      TEXT,
    tentativas    INTEGER NOT NULL DEFAULT 0,
    dados         TEXT NOT NULL DEFAULT '{}',
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (job, video_id)
);
"""


def _agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class RegistroVideo:
    """Uma linha da tabela de estado."""

    job: str
    video_id: str
    tipo: str | None
    status: str
    titulo: str | None
    erro: str | None
    mensagem: str | None
    tentativas: int
    dados: dict[str, Any]
    criado_em: str
    atualizado_em: str


class Estado:
    """Acesso ao banco de estado. Use como gerenciador de contexto ou chame :meth:`fechar`."""

    def __init__(self, caminho: Path) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho = caminho
        self._con = sqlite3.connect(caminho)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(_ESQUEMA)

    def __enter__(self) -> Estado:
        return self

    def __exit__(self, *exc: object) -> None:
        self.fechar()

    def fechar(self) -> None:
        """Fecha a conexão."""
        self._con.close()

    @contextmanager
    def _transacao(self) -> Iterator[sqlite3.Connection]:
        with self._con:
            yield self._con

    def obter(self, job: str, video_id: str) -> RegistroVideo | None:
        """Retorna o registro do vídeo, ou ``None`` se não existir."""
        linha = self._con.execute(
            "SELECT * FROM videos WHERE job = ? AND video_id = ?", (job, video_id)
        ).fetchone()
        return _registro(linha) if linha else None

    def listar(
        self, job: str, *, status: str | None = None, tipo: str | None = None
    ) -> list[RegistroVideo]:
        """Lista os vídeos de um job, opcionalmente filtrando por status e tipo."""
        sql = "SELECT * FROM videos WHERE job = ?"
        args: list[Any] = [job]
        if status is not None:
            sql += " AND status = ?"
            args.append(status)
        if tipo is not None:
            sql += " AND tipo = ?"
            args.append(tipo)
        sql += " ORDER BY criado_em, video_id"
        return [_registro(r) for r in self._con.execute(sql, args)]

    def registrar(
        self,
        job: str,
        video_id: str,
        status: Status,
        *,
        tipo: str | None = None,
        titulo: str | None = None,
        dados: dict[str, Any] | None = None,
        permitir_regredir: bool = False,
    ) -> RegistroVideo:
        """Cria ou atualiza o vídeo, limpando o erro.

        O status só avança, a menos que ``permitir_regredir=True`` (usado por ``--forcar``).
        ``dados`` é mesclado ao que já existe.
        """
        atual = self.obter(job, video_id)
        agora = _agora()
        with self._transacao() as con:
            if atual is None:
                con.execute(
                    "INSERT INTO videos (job, video_id, tipo, status, titulo, dados, criado_em,"
                    " atualizado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (job, video_id, tipo, status, titulo, json.dumps(dados or {}), agora, agora),
                )
            else:
                novo_status = status
                if not permitir_regredir and ORDEM[status] < ORDEM[atual.status]:
                    novo_status = atual.status  # type: ignore[assignment]
                mesclado = {**atual.dados, **(dados or {})}
                con.execute(
                    "UPDATE videos SET tipo = ?, status = ?, titulo = ?, dados = ?, erro = NULL,"
                    " mensagem = NULL, tentativas = 0, atualizado_em = ?"
                    " WHERE job = ? AND video_id = ?",
                    (
                        tipo if tipo is not None else atual.tipo,
                        novo_status,
                        titulo if titulo is not None else atual.titulo,
                        json.dumps(mesclado),
                        agora,
                        job,
                        video_id,
                    ),
                )
        registro = self.obter(job, video_id)
        assert registro is not None
        return registro

    def marcar_erro(self, job: str, video_id: str, etapa: str, mensagem: str) -> RegistroVideo:
        """Registra um erro na etapa sem mudar o status (cria como ``listado`` se preciso)."""
        agora = _agora()
        with self._transacao() as con:
            con.execute(
                "INSERT INTO videos (job, video_id, status, erro, mensagem, tentativas, criado_em,"
                " atualizado_em) VALUES (?, ?, 'listado', ?, ?, 1, ?, ?)"
                " ON CONFLICT (job, video_id) DO UPDATE SET erro = excluded.erro,"
                " mensagem = excluded.mensagem, tentativas = videos.tentativas + 1,"
                " atualizado_em = excluded.atualizado_em",
                (job, video_id, etapa, mensagem, agora, agora),
            )
        registro = self.obter(job, video_id)
        assert registro is not None
        return registro


def _registro(linha: sqlite3.Row) -> RegistroVideo:
    d = dict(linha)
    d["dados"] = json.loads(d["dados"] or "{}")
    return RegistroVideo(**d)


def abrir_estado(pasta_saida: Path) -> Estado:
    """Abre (criando se preciso) o banco de estado em ``<pasta_saida>/estado.db``."""
    return Estado(pasta_saida / "estado.db")
