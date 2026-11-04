# Configuração (`config.yaml`)

O arquivo `config.yaml` fica **fora do git** (contém IDs de canal e playlists). Comece copiando o exemplo:

```powershell
copy config.example.yaml config.yaml
yt-thumbnail validar
```

O caminho pode ser trocado com `--config` ou com a variável de ambiente `YT_THUMBNAIL_CONFIG`. Caminhos relativos são resolvidos a partir da pasta do `config.yaml`.

## `caminhos`

| Chave | Padrão | Descrição |
|---|---|---|
| `saida` | `saida` | artefatos por job/vídeo (`saida/<job>/<video_id>/`) |
| `secrets` | `secrets` | `client_secret.json` e `tokens/<channel_id>.json` |
| `presets` | `presets` | pasta dos presets YAML |
| `prompts` | `prompts` | templates de prompt |

## `gpu`

| Chave | Padrão | Descrição |
|---|---|---|
| `transcricao` | `0` | índice da GPU do faster-whisper |
| `imagem` | `1` | índice da GPU do SDXL |

Com uma GPU só, use `0` nas duas.

## `transcricao`

| Chave | Padrão | Descrição |
|---|---|---|
| `idiomas` | `["pt.*", "pt"]` | idiomas de legenda aceitos |
| `modelo_whisper` | `large-v3` | modelo do faster-whisper (`large-v3`, `turbo`, ...) |
| `compute_type` | `float16` | precisão na GPU |

## `analise`

| Chave | Padrão | Descrição |
|---|---|---|
| `backend` | `claude_code` | backend de análise (`claude -p`) |
| `tentativas` | `2` | novas tentativas se o JSON vier inválido |
| `max_caracteres_transcricao` | `20000` | acima disso a transcrição é truncada/resumida |

## `imagem`

| Chave | Padrão | Descrição |
|---|---|---|
| `modelo` | `stabilityai/stable-diffusion-xl-base-1.0` | modelo do Hugging Face |
| `variacoes` | `3` | variações por vídeo |

## `formatos`

Resoluções `[largura, altura]` por tipo. `geracao` deve ser múltipla de 8.

| Tipo | `geracao` | `saida` |
|---|---|---|
| `longo` | `[1344, 768]` | `[1280, 720]` |
| `short` | `[768, 1344]` | `[1080, 1920]` |

## `envio`

| Chave | Padrão | Descrição |
|---|---|---|
| `pausa_segundos` | `[5, 10]` | pausa aleatória entre envios |

## `canais`

Mapa `apelido → canal`. O apelido usa letras minúsculas, números, `-` e `_`.

| Chave | Padrão | Descrição |
|---|---|---|
| `channel_id` | `null` | ID do canal (`UC...`, 24 caracteres); preenchido pelo `yt-thumbnail auth` |
| `shorts_capa_personalizada` | `false` | `true` só para canais no Programa de Parcerias (ver `docs/shorts.md`) |

## `jobs`

Lista de associações playlist → canal → preset.

| Chave | Obrigatória | Descrição |
|---|---|---|
| `nome` | sim | identificador único (vira a pasta `saida/<nome>/`) |
| `playlist` | sim | URL pública com `list=` |
| `canal` | sim | apelido definido em `canais` |
| `preset` | sim | nome de um arquivo em `presets/` (sem `.yaml`) |
| `tipos` | não | `[longo]` (padrão) ou `[longo, short]` |

A validação acusa: chaves desconhecidas (erros de digitação), job apontando para canal inexistente, preset ausente ou inválido, nomes de job repetidos e `channel_id` mal formado.
