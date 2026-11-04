# Uso da CLI

Todos os comandos têm ajuda: `yt-thumbnail --help` e `yt-thumbnail <comando> --help`.

## Opções globais

| Opção | Descrição |
|---|---|
| `--version`, `-V` | mostra a versão |

## Comandos disponíveis

### `yt-thumbnail ambiente [--raiz .]`

Verifica Python, GPUs/VRAM, PyTorch+CUDA, bibliotecas de GPU, FFmpeg, yt-dlp, Claude Code e as fontes dos presets. Sai com código 1 se algum item obrigatório falhar.

### `yt-thumbnail validar [--config config.yaml]`

Valida o `config.yaml` e todos os presets usados pelos jobs; lista os jobs encontrados.

## Comandos planejados

`listar`, `transcrever`, `analisar`, `gerar`, `compor`, `revisar`, `aprovar`, `rejeitar`, `enviar`, `restaurar`, `auth`, `canais`, `tudo` — entram nas próximas fases (ver `PLANO.md`).
