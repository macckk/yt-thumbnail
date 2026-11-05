# SPDX-License-Identifier: GPL-3.0-or-later
"""Backend de análise padrão: Claude Code em modo headless (``claude -p``).

O prompt vai pela entrada padrão; a resposta vem em ``--output-format json``. Com
``saida_estruturada``, o esquema é passado em ``--json-schema``. As ferramentas são
desligadas (``--tools ""``) e a sessão não é gravada: é uma chamada de texto pura.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from typing import Any

from yt_thumbnail.analise.base import ErroBackend

_DICA_LOGIN = (
    "O Claude Code não está autenticado nesta sessão. Rode `claude` uma vez e faça login; "
    "se estiver usando por SSH, gere um token com `claude setup-token` e defina "
    "CLAUDE_CODE_OAUTH_TOKEN (ver docs/solucao-de-problemas.md)."
)


class ClaudeCodeBackend:
    """Chama o executável ``claude`` do Claude Code."""

    nome = "claude_code"

    def __init__(
        self,
        modelo: str | None = None,
        timeout: float = 300,
        saida_estruturada: bool = True,
        executavel: str | None = None,
    ) -> None:
        self.modelo = modelo
        self.timeout = timeout
        self.saida_estruturada = saida_estruturada
        self.executavel = executavel

    def comando(self, esquema: dict[str, Any]) -> list[str]:
        """Linha de comando (sem o prompt, que vai pela entrada padrão)."""
        exe = self.executavel or shutil.which("claude")
        if exe is None:
            raise ErroBackend(
                "Comando `claude` não encontrado no PATH. Instale o Claude Code "
                "(docs/instalacao-windows.md, passo 6)."
            )
        cmd = [exe, "-p", "--output-format", "json", "--no-session-persistence", "--tools", ""]
        if self.saida_estruturada:
            cmd += ["--json-schema", json.dumps(esquema, ensure_ascii=False)]
        if self.modelo:
            cmd += ["--model", self.modelo]
        return cmd

    def gerar(self, prompt: str, esquema: dict[str, Any]) -> str:
        """Executa ``claude -p`` e devolve o JSON da resposta como texto.

        Raises:
            ErroBackend: executável ausente, sem login, tempo esgotado ou erro do CLI.
        """
        cmd = self.comando(esquema)
        with tempfile.TemporaryDirectory(prefix="yt-thumbnail-") as pasta:
            try:
                r = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout,
                    cwd=pasta,
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise ErroBackend(
                    f"`claude -p` não respondeu em {self.timeout:.0f} s "
                    "(aumente analise.timeout_segundos)"
                ) from e
            except OSError as e:
                raise ErroBackend(f"não foi possível executar `claude`: {e}") from e
        return interpretar_saida(r.stdout, r.stderr, r.returncode)


def interpretar_saida(stdout: str, stderr: str, codigo: int) -> str:
    """Interpreta a saída ``--output-format json`` do ``claude -p``.

    Returns:
        O JSON da resposta como texto (``structured_output`` se houver; senão ``result``).

    Raises:
        ErroBackend: se o CLI indicar erro.
    """
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        detalhe = (stderr or stdout).strip()[-500:] or f"código de saída {codigo}"
        if "login" in detalhe.lower():
            raise ErroBackend(_DICA_LOGIN) from None
        raise ErroBackend(f"`claude -p` falhou: {detalhe}") from None
    if isinstance(envelope, list):  # alguns modos devolvem a lista de eventos
        resultados = [e for e in envelope if isinstance(e, dict) and e.get("type") == "result"]
        envelope = resultados[-1] if resultados else {}
    resultado = envelope.get("result")
    if envelope.get("is_error"):
        texto = str(resultado or envelope.get("subtype") or "erro desconhecido")
        if "logged in" in texto.lower() or "/login" in texto:
            raise ErroBackend(_DICA_LOGIN)
        raise ErroBackend(f"`claude -p` respondeu com erro: {texto}")
    estruturado = envelope.get("structured_output")
    if isinstance(estruturado, dict):
        return json.dumps(estruturado, ensure_ascii=False)
    if not isinstance(resultado, str) or not resultado.strip():
        raise ErroBackend("`claude -p` não devolveu resposta")
    return resultado
