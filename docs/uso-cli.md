# Uso da CLI

Todos os comandos têm ajuda: `yt-thumbnail --help` e `yt-thumbnail <comando> --help`.

## Opções globais

| Opção | Descrição |
|---|---|
| `--version`, `-V` | mostra a versão |

## Opções comuns das etapas

| Opção | Descrição |
|---|---|
| `--config`, `-c` | arquivo de configuração (padrão: `$YT_THUMBNAIL_CONFIG` ou `./config.yaml`) |
| `--job`, `-j` | processa só este job (padrão: todos) |
| `--ids a,b,c` | restringe a estes IDs de vídeo |
| `--forcar` | refaz a etapa mesmo que o artefato já exista |

Toda etapa é idempotente: rodar de novo só processa o que falta. Erros de um vídeo ficam registrados no estado e não interrompem o lote; o comando sai com código 1 se houve erro.

## Comandos disponíveis

### `yt-thumbnail ambiente [--raiz .]`

Verifica Python, GPUs/VRAM, PyTorch+CUDA, bibliotecas de GPU, FFmpeg, yt-dlp, Claude Code e as fontes dos presets. Sai com código 1 se algum item obrigatório falhar.

### `yt-thumbnail validar [--config config.yaml]`

Valida o `config.yaml` e todos os presets usados pelos jobs; lista os jobs encontrados.

### `yt-thumbnail listar [--job nome] [--ids ...] [--forcar]`

Lê a playlist de cada job com o yt-dlp (sem API key e sem baixar mídia), consulta os metadados de cada vídeo e detecta o tipo:

- **Short**: duração ≤ 180 s **e** vertical (altura > largura);
- **longo**: todo o resto.

Grava `saida/<job>/<video_id>/meta.json` e registra o vídeo como `listado`. Mostra uma tabela com tipo, duração, dimensões e título; vídeos de um tipo que não está em `tipos` do job aparecem como "fora do job" (são listados, mas as próximas etapas os ignoram). Avisa se algum vídeo não for do `channel_id` configurado para o canal do job.

```powershell
yt-thumbnail listar
yt-thumbnail listar --job meditacoes
yt-thumbnail listar --job meditacoes --ids ID_DO_VIDEO --forcar
```

### `yt-thumbnail transcrever [--job] [--ids] [--tipo longo|short] [--forcar] [--forcar-whisper] [--limite N]`

Transcreve os vídeos já listados cujo tipo está em `tipos` do job:

1. **legenda do YouTube** (manual tem preferência sobre a automática), nos idiomas de `transcricao.idiomas`;
2. sem legenda, ou se o YouTube bloquear o download dela (HTTP 429): baixa só o áudio e transcreve com o **faster-whisper** na GPU `gpu.transcricao`;
3. sem fala (ex.: Short só com música): marca `sem_fala`; a análise usará título e descrição.

Grava `transcricao.txt` e `transcricao.json` e registra o status `transcrito`.

| Opção | Descrição |
|---|---|
| `--tipo` | só `longo` ou só `short` |
| `--forcar-whisper` | ignora a legenda e transcreve com o Whisper (útil quando a legenda automática é ruim) |
| `--limite N` | processa no máximo N vídeos pendentes (bom para testar) |

```powershell
yt-thumbnail transcrever --job palestras --limite 3
yt-thumbnail transcrever --ids ID_DO_VIDEO --forcar-whisper
```

## Comandos planejados

`analisar`, `gerar`, `compor`, `revisar`, `aprovar`, `rejeitar`, `enviar`, `restaurar`, `auth`, `canais`, `tudo` — entram nas próximas fases (ver `PLANO.md`).
