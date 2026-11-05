# yt-thumbnail

Gerador automático de capas (thumbnails) para playlists do YouTube, rodando **localmente** num PC Windows com GPU NVIDIA.

Para cada vídeo (longo ou Short) de uma playlist pública dos seus canais:

1. obtém a transcrição (legenda do YouTube ou `faster-whisper` na GPU);
2. analisa o conteúdo com o Claude Code e gera um prompt de imagem e um título curto, conforme um **preset** de identidade visual;
3. gera a imagem com **SDXL 1.0** local (sem texto);
4. escreve o título com Pillow;
5. gera uma página HTML para **revisão humana** (antes × depois);
6. envia a capa aprovada pela YouTube Data API, no canal certo.

> **Status:** em desenvolvimento — Fase 1 (listagem da playlist e detecção longo/Short). Veja o [CHANGELOG](CHANGELOG.md) e o [plano](PLANO.md).

## Requisitos

- Windows 10/11 (Linux deve funcionar, mas não é testado)
- Python 3.11+
- GPU NVIDIA com 8 GB de VRAM (recomendado: 2 GPUs — uma para transcrição, outra para imagem)
- [FFmpeg](https://ffmpeg.org/) e [Claude Code](https://claude.com/claude-code)
- ~15 GB livres para os modelos (baixados do Hugging Face na primeira execução)

## Início rápido

```powershell
git clone https://github.com/macckk/yt-thumbnail.git
cd yt-thumbnail
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python scripts/baixar_fontes.py
copy config.example.yaml config.yaml
yt-thumbnail ambiente
```

Passo a passo completo (drivers, CUDA, PyTorch, FFmpeg): [docs/instalacao-windows.md](docs/instalacao-windows.md).

## Importante

- **Cada pessoa cria o seu próprio OAuth client** no Google Cloud — o projeto não distribui credenciais.
- **Os modelos não são distribuídos** neste repositório; são baixados do Hugging Face na primeira execução, sob as licenças deles (ver [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).
- `config.yaml`, `secrets/` e `saida/` ficam fora do git. Veja [SECURITY.md](SECURITY.md).
- Capas personalizadas em Shorts só estão disponíveis para canais do Programa de Parcerias do YouTube.

## Documentação

| Documento | Conteúdo |
|---|---|
| [Instalação no Windows](docs/instalacao-windows.md) | do zero até `yt-thumbnail ambiente` OK |
| [Configuração](docs/configuracao.md) | referência do `config.yaml` |
| [Presets](docs/presets.md) | identidade visual e como criar novos |
| [Uso da CLI](docs/uso-cli.md) | comandos e opções |
| [Arquitetura](docs/arquitetura.md) | fluxo, estados e arquivos |
| [Solução de problemas](docs/solucao-de-problemas.md) | erros comuns |

## Licença

Copyright (C) 2026 macckk.

Este programa é software livre: você pode redistribuí-lo e/ou modificá-lo sob os termos da **GNU General Public License v3.0 ou posterior** (`GPL-3.0-or-later`). Veja [LICENSE](LICENSE). Componentes de terceiros (modelos, fontes, bibliotecas) têm licenças próprias, listadas em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
