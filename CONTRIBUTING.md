# Como contribuir

Obrigado pelo interesse! Contribuições são bem-vindas e ficam sob a **GPL-3.0-or-later**.

## Ambiente de desenvolvimento

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Os testes não precisam de GPU (as partes pesadas usam mocks).

```powershell
ruff check .
ruff format --check .
pytest
```

## Padrões

- Código, mensagens e documentação em português.
- Type hints em todo o código e docstring em toda função pública.
- `# SPDX-License-Identifier: GPL-3.0-or-later` no topo de cada arquivo `.py`.
- `pathlib` em vez de caminhos fixos; nada de dados pessoais (IDs de canal, playlists, tokens) em commits.
- Toda mudança de comportamento atualiza os `docs/` correspondentes e o `CHANGELOG.md`.

## Commits

Mensagens curtas no imperativo, de preferência no estilo [Conventional Commits](https://www.conventionalcommits.org/pt-br/): `feat: ...`, `fix: ...`, `docs: ...`, `test: ...`.

## Criar um preset

Veja [docs/presets.md](docs/presets.md). Presets novos são uma ótima primeira contribuição.

## Shorts

O envio de capas de Shorts precisa de um canal no Programa de Parcerias do YouTube; se você tiver um, testes e relatos ajudam muito.
