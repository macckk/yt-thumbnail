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
| `imagem` | `1` | índice da GPU do SDXL (só o UNet, ~5 GB + ativações) |
| `texto_sdxl` | `null` | GPU dos codificadores de texto e do VAE do SDXL; `null` = a de `transcricao` |

Em placas de 8 GB o SDXL inteiro não cabe numa GPU só em 1344×768. Por isso, com duas GPUs, o trabalho é dividido: o UNet (a difusão) fica na GPU `imagem`, e os codificadores de texto (~1,6 GB) e o VAE em fp32 (decodificação final) ficam na GPU `texto_sdxl`. Medido em 2× RTX 3060 Ti: pico de ~6,1 GB na GPU de imagem e ~8 GB na outra (o cache do PyTorch ocupa o que estiver livre). Não rode `transcrever` e `gerar` ao mesmo tempo.

Com uma GPU só, use `0` em todas e ligue `imagem.cpu_offload` (8 GB) se faltar memória.

## `ytdlp`

| Chave | Padrão | Descrição |
|---|---|---|
| `cookies_navegador` | `null` | navegador de onde o yt-dlp lê cookies (`firefox`, `chrome`, `edge`...). Use só se o YouTube bloquear o yt-dlp ("Sign in to confirm you're not a bot") |

## `transcricao`

| Chave | Padrão | Descrição |
|---|---|---|
| `idiomas` | `["pt", "pt-BR", "pt.*"]` | idiomas de legenda aceitos, em ordem de preferência (expressões regulares) |
| `idioma_whisper` | `pt` | idioma passado ao faster-whisper |
| `modelo_whisper` | `large-v3` | modelo do faster-whisper (`large-v3`, `turbo`, ...); baixado do Hugging Face no primeiro uso |
| `compute_type` | `float16` | precisão na GPU |
| `manter_audio` | `false` | `true` guarda o `audio.*` depois de transcrever (cada palestra de 40 min tem ~40 MB) |
| `whisper_se_legenda_falhar` | `true` | se o download da legenda falhar (ex.: HTTP 429), transcreve com o Whisper em vez de registrar erro |
| `pausa_legendas_segundos` | `1` | pausa entre downloads de legenda, para reduzir bloqueios |

## `analise`

| Chave | Padrão | Descrição |
|---|---|---|
| `backend` | `claude_code` | backend de análise (`claude -p`) |
| `modelo` | `null` | modelo passado ao backend (ex.: `sonnet`, `opus`); `null` usa o padrão do Claude Code |
| `tentativas` | `2` | novas tentativas se a resposta vier inválida |
| `max_caracteres_transcricao` | `20000` | acima disso, usa início + meio + fim da transcrição |
| `timeout_segundos` | `300` | tempo máximo de cada chamada |
| `saida_estruturada` | `true` | passa o esquema JSON ao `claude` (`--json-schema`); desligue se a sua versão do Claude Code não aceitar |
| `template` | `analise.md` | template do prompt, em `caminhos.prompts` |

## `imagem`

| Chave | Padrão | Descrição |
|---|---|---|
| `modelo` | `stabilityai/stable-diffusion-xl-base-1.0` | modelo do Hugging Face (variante fp16) |
| `variacoes` | `3` | variações por vídeo |
| `attention_slicing` | `false` | reduz o pico de VRAM, um pouco mais lento |
| `cpu_offload` | `false` | mantém partes do modelo na RAM e move para a GPU sob demanda; bem mais lento e usa mais RAM — último recurso |

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

Todos os vídeos da playlist são listados e classificados, mas só os tipos em `tipos` seguem para as próximas etapas. Os outros aparecem como "fora do job" no `yt-thumbnail listar`.

## Arquivos gerados

- `saida/estado.db`: estado de cada vídeo (SQLite), ver [arquitetura.md](arquitetura.md).
- `saida/<job>/<video_id>/`: artefatos de cada vídeo, começando por `meta.json`.

A validação acusa: chaves desconhecidas (erros de digitação), job apontando para canal inexistente, preset ausente ou inválido, nomes de job repetidos e `channel_id` mal formado.
