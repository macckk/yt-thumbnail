# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Fase 0 — Ambiente, esqueleto e verificação
- Estrutura do projeto, `pyproject.toml` (pacote `yt_thumbnail`, comando `yt-thumbnail`, licença GPL-3.0-or-later).
- Dependências base e extras `[gpu]` e `[dev]`.
- `config.py`: carga e validação do `config.yaml` com pydantic (jobs, canais, formatos, GPUs, referências cruzadas).
- `presets.py` e o primeiro preset, `presets/espiritualidade.yaml`.
- Template `prompts/analise.md`.
- Comandos `yt-thumbnail ambiente` e `yt-thumbnail validar`; `scripts/check_env.py`.
- `scripts/baixar_fontes.py` (fontes OFL do Google Fonts).
- CI no GitHub Actions (ruff + pytest, sem GPU).
- Documentação: README, instalação no Windows, configuração, presets, uso da CLI, solução de problemas.
