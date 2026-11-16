# SPDX-License-Identifier: GPL-3.0-or-later
"""Servidor local da revisão: aprovar e rejeitar pelos botões da página.

``yt-thumbnail revisar --servir`` serve ``saida/<job>/revisao.html`` em
``http://127.0.0.1:<porta>/`` e recebe as decisões por ``POST /api/...``, gravando no
mesmo estado que os comandos ``aprovar`` e ``rejeitar``. Depois de cada decisão a página é
regravada (só os pendentes).

Segurança: escuta só em 127.0.0.1, confere o cabeçalho ``Host`` (contra DNS rebinding) e
exige, em todo POST, um token aleatório que só vai dentro da página servida. Só serve
``revisao.html`` e imagens das pastas dos jobs configurados. Nada aqui envia capas ao
YouTube: o envio continua sendo ``enviar --aprovados``.
"""

from __future__ import annotations

import html
import json
import secrets
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from yt_thumbnail.estado import abrir_estado
from yt_thumbnail.revisao import ErroRevisao, aprovar, pendentes, preparar_revisao, rejeitar

PORTA_PADRAO = 8765
PAGINA = "revisao.html"
TIPOS_IMAGEM = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
TAMANHO_MAXIMO_POST = 16 * 1024


class ServidorRevisao(HTTPServer):
    """HTTPServer com a configuração da revisão (um pedido por vez)."""

    def __init__(
        self,
        pasta_saida: Path,
        tipos_por_job: Mapping[str, list[str]],
        porta: int = PORTA_PADRAO,
        *,
        token: str | None = None,
        ao_decidir: Callable[[str], None] | None = None,
    ) -> None:
        self.pasta_saida = pasta_saida
        self.tipos_por_job = dict(tipos_por_job)
        self.token = token or secrets.token_urlsafe(24)
        self.ao_decidir = ao_decidir
        super().__init__(("127.0.0.1", porta), _Pedido)

    @property
    def porta(self) -> int:
        return self.server_address[1]

    def url(self, job: str | None = None) -> str:
        base = f"http://127.0.0.1:{self.porta}/"
        return base + (f"{job}/{PAGINA}" if job else "")

    def regravar_pagina(self, estado, job: str) -> int:  # noqa: ANN001
        """Regrava a página do job (sem rede) e devolve quantos ainda aguardam."""
        tipos = self.tipos_por_job[job]
        preparar_revisao(
            job=job, pasta_saida=self.pasta_saida, estado=estado, tipos=tipos, baixar=None
        )
        return len(pendentes(estado, job, tipos))


class _Pedido(BaseHTTPRequestHandler):
    server: ServidorRevisao
    server_version = "yt-thumbnail"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silencioso: as decisões são relatadas por ``ao_decidir``."""

    # ------------------------------------------------------------------ respostas

    def _enviar(self, status: HTTPStatus, corpo: bytes, tipo: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, status: HTTPStatus, **dados: object) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self._enviar(status, corpo, "application/json; charset=utf-8")

    def _erro(self, status: HTTPStatus, mensagem: str) -> None:
        self._enviar(status, mensagem.encode("utf-8"), "text/plain; charset=utf-8")

    def _host_valido(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{self.server.porta}", f"localhost:{self.server.porta}"}

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_valido():
            self._erro(HTTPStatus.FORBIDDEN, "host não permitido")
            return
        partes = [unquote(p) for p in urlsplit(self.path).path.split("/") if p]
        jobs = self.server.tipos_por_job
        if not partes:
            self._indice()
            return
        job = partes[0]
        if job not in jobs or any(p in (".", "..") or "\\" in p for p in partes):
            self._erro(HTTPStatus.NOT_FOUND, "não encontrado")
            return
        if partes[1:] == [PAGINA]:
            self._pagina(job)
            return
        pasta_job = (self.server.pasta_saida / job).resolve()
        arquivo = pasta_job.joinpath(*partes[1:]).resolve()
        tipo = TIPOS_IMAGEM.get(arquivo.suffix.lower())
        if tipo is None or not arquivo.is_relative_to(pasta_job) or not arquivo.is_file():
            self._erro(HTTPStatus.NOT_FOUND, "não encontrado")
            return
        self._enviar(HTTPStatus.OK, arquivo.read_bytes(), tipo)

    do_HEAD = do_GET  # noqa: N815

    def _indice(self) -> None:
        jobs = list(self.server.tipos_por_job)
        if len(jobs) == 1:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", f"/{jobs[0]}/{PAGINA}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        itens = "".join(
            f"<li><a href='/{html.escape(j)}/{PAGINA}'>{html.escape(j)}</a></li>" for j in jobs
        )
        corpo = (
            "<!doctype html><meta charset='utf-8'><title>Revisão</title>"
            "<body style='font-family:system-ui;padding:16px'>"
            f"<h1>Revisão das capas</h1><ul>{itens}</ul></body>"
        )
        self._enviar(HTTPStatus.OK, corpo.encode("utf-8"), "text/html; charset=utf-8")

    def _pagina(self, job: str) -> None:
        arquivo = self.server.pasta_saida / job / PAGINA
        if not arquivo.is_file():
            with abrir_estado(self.server.pasta_saida) as estado:
                self.server.regravar_pagina(estado, job)
        texto = arquivo.read_text(encoding="utf-8")
        meta = f'<meta name="yt-token" content="{html.escape(self.server.token)}">'
        texto = texto.replace("<head>", "<head>\n" + meta, 1)
        self._enviar(HTTPStatus.OK, texto.encode("utf-8"), "text/html; charset=utf-8")

    # ------------------------------------------------------------------ POST

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_valido():
            self._erro(HTTPStatus.FORBIDDEN, "host não permitido")
            return
        if not secrets.compare_digest(self.headers.get("X-Token", ""), self.server.token):
            self._json(
                HTTPStatus.FORBIDDEN, ok=False, mensagem="token inválido; recarregue a página"
            )
            return
        acao = urlsplit(self.path).path.removeprefix("/api/")
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            if not 0 < tamanho <= TAMANHO_MAXIMO_POST:
                raise ValueError("corpo vazio ou grande demais")
            dados = json.loads(self.rfile.read(tamanho))
            if not isinstance(dados, dict):
                raise ValueError("JSON deve ser um objeto")
        except ValueError as e:
            self._json(HTTPStatus.BAD_REQUEST, ok=False, mensagem=f"pedido inválido: {e}")
            return
        job = dados.get("job")
        if job not in self.server.tipos_por_job:
            self._json(HTTPStatus.BAD_REQUEST, ok=False, mensagem=f"job desconhecido: {job}")
            return
        try:
            with abrir_estado(self.server.pasta_saida) as estado:
                mensagem = self._decidir(estado, acao, job, dados)
                restantes = self.server.regravar_pagina(estado, job)
        except (ErroRevisao, ValueError, TypeError) as e:
            self._json(HTTPStatus.BAD_REQUEST, ok=False, mensagem=str(e))
            return
        if self.server.ao_decidir is not None:
            self.server.ao_decidir(mensagem)
        self._json(HTTPStatus.OK, ok=True, mensagem=mensagem, restantes=restantes)

    def _decidir(self, estado, acao: str, job: str, dados: dict) -> str:  # noqa: ANN001
        pasta = self.server.pasta_saida
        if acao == "aprovar":
            vid, variacao = str(dados.get("video", "")), _inteiro(dados.get("variacao"))
            aprovar(estado, pasta, job, vid, variacao)
            return f"aprovado {job}/{vid}: variação {variacao}"
        if acao == "rejeitar":
            vid = str(dados.get("video", ""))
            rejeitar(estado, job, vid)
            return f"rejeitado {job}/{vid}"
        if acao == "aprovar-todos":
            variacao = _inteiro(dados.get("variacao"))
            alvos = pendentes(estado, job, self.server.tipos_por_job[job])
            for vid in alvos:
                aprovar(estado, pasta, job, vid, variacao)
            return f"aprovados {len(alvos)} vídeo(s) de {job}: variação {variacao}"
        raise ValueError(f"ação desconhecida: {acao}")


def _inteiro(valor: object) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int | str):
        raise ValueError("variação inválida")
    try:
        return int(valor)
    except ValueError as e:
        raise ValueError("variação inválida") from e
