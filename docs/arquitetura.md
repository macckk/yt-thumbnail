# Arquitetura

> Documento em construção: cada fase acrescenta a sua parte (ver `PLANO.md`).

## Fluxo

```
playlist (yt-dlp) ─► listar ─► transcrever ─► analisar ─► gerar ─► compor ─► revisar ─► aprovar ─► enviar
                     Fase 1     Fase 2         Fase 3      Fase 4   Fase 5    Fase 6               Fase 7
```

Cada etapa lê os artefatos da anterior em `saida/<job>/<video_id>/` e atualiza o estado do vídeo.

## Estados

```
listado → transcrito → analisado → imagens_geradas → capas_compostas → aprovado → enviado
                                                                       ↘ rejeitado
                                                            aprovado → nao_elegivel (Short em canal sem capa personalizada)
(listado … capas_compostas) → ignorado (`selecionar`: fica com a capa atual) → volta ao status anterior com --incluir
```

`ignorado` tem a ordem mais alta, então o `listar` (que registra `listado` sem regredir) não o traz de volta, e `Estado.listar` o deixa de fora: nenhuma etapa o vê. O status anterior fica em `dados.status_antes`.

O estado fica em `saida/estado.db` (SQLite, módulo `estado.py`), uma linha por `(job, video_id)`:

| Coluna | Descrição |
|---|---|
| `status` | último estado alcançado; **só avança** (exceto com `--forcar`) |
| `tipo` | `longo` ou `short` |
| `erro`, `mensagem`, `tentativas` | última etapa que falhou, a mensagem e quantas vezes falhou; limpos quando a etapa dá certo |
| `dados` | JSON com informações auxiliares (ex.: `channel_id`, posição na playlist, seeds) |

Um erro **não** muda o status: o vídeo continua onde estava e é tentado de novo na próxima execução.

## Módulos

| Módulo | Papel |
|---|---|
| `config.py` | carga e validação do `config.yaml` (pydantic) |
| `presets.py` | carga e validação dos presets |
| `estado.py` | estado por vídeo (SQLite) |
| `playlist.py` | Fase 1: listagem e detecção de tipo |
| `transcricao.py` | Fase 2: legenda do YouTube e faster-whisper |
| `analise/base.py` | Fase 3: interface dos backends, prompt, validação e novas tentativas |
| `analise/claude_code.py` | Fase 3: backend padrão (`claude -p`) |
| `imagem.py` | Fase 4: SDXL, variações e ajuste para a saída |
| `composicao.py` | Fase 5: título sobre as imagens (Pillow), capas e miniaturas |
| `revisao.py` | Fase 6: backup da capa atual, página de revisão, aprovar/rejeitar |
| `selecao.py` | `selecionar`: quais vídeos ganham capa nova (status `ignorado`) e a página de seleção |
| `servidor.py` | servidor local da revisão e da seleção (`revisar --servir`, `selecionar`): botões |
| `youtube_api.py` | Fase 7: OAuth por canal, envio e restauração |
| `orquestracao.py` | Fase 8: `tudo`, liberação de memória entre etapas, resumo do estado |
| `ambiente.py` | verificação do ambiente |
| `cli.py` | comandos (Typer) |

## Fase 1 — Listagem e detecção de tipo

1. `yt-dlp` com `extract_flat` lista os IDs da playlist (equivale a `yt-dlp --flat-playlist -J`). Se ele ler menos do que o `playlist_count` informado (o yt-dlp às vezes para na primeira página, 100 vídeos), `completar` busca os IDs pela YouTube Data API (`playlistItems.list`, 50 por página, só `public`/`unlisted`) com o token do canal do job; a ordem passa a ser a da API.
2. Para cada ID sem `meta.json` válido, uma chamada de metadados completa (sem download) traz duração, largura/altura, `channel_id`, título, descrição e URL da capa atual.
3. Classificação (`playlist.classificar`):
   - duração > 180 s → **longo**;
   - duração ≤ 180 s e altura > largura → **short**;
   - duração ≤ 180 s e horizontal/quadrado → **longo**;
   - sem dimensões e duração ≤ 180 s → consulta `https://www.youtube.com/shorts/<id>` sem seguir redirecionamento (200 = Short; redirecionamento = não é). `tipo_origem` registra qual regra decidiu.
4. Grava `meta.json` (escrita atômica) e registra `listado`.

Idempotência: com `meta.json` válido, o vídeo não é consultado de novo; só a posição na playlist é atualizada. Um `meta.json` corrompido é refeito.

### `meta.json`

```json
{
  "video_id": "abc123",
  "titulo": "...",
  "descricao": "...",
  "url": "https://www.youtube.com/watch?v=abc123",
  "duracao": 45.0,
  "largura": 1080,
  "altura": 1920,
  "tipo": "short",
  "tipo_origem": "dimensoes",
  "channel_id": "UC...",
  "canal_nome": "...",
  "thumbnail_url": "https://i.ytimg.com/vi/abc123/maxresdefault.jpg",
  "data_publicacao": "2026-01-02",
  "indice_playlist": 3,
  "listado_em": "2026-11-05T20:00:00+00:00"
}
```

## Fase 2 — Transcrição

Para cada vídeo listado cujo tipo está em `tipos` do job (e sem `transcricao.json` válido):

1. **Legenda** (`transcricao.obter_legenda`): uma consulta de metadados mostra as faixas disponíveis; escolhe a primeira que casa com `transcricao.idiomas`, **manual antes de automática**, e baixa só ela em VTT para `legenda.vtt`.
2. **Limpeza** (`limpar_vtt`): remove cabeçalho, `NOTE`, timestamps, tags de tempo/estilo (`<c>`, `<00:00:01.000>`), marcações como `[Música]` e as linhas repetidas que a legenda automática gera (cada bloco repete a linha anterior).
3. **Whisper** (sem legenda, legenda vazia, `--forcar-whisper` ou falha no download da legenda): baixa só o áudio (`bestaudio`), transcreve com `faster-whisper` (`device="cuda"`, `device_index=gpu.transcricao`, `vad_filter=True`) e apaga o áudio (a menos que `manter_audio`). O modelo é carregado uma vez por execução.
4. **Sem fala**: se o texto final tiver menos de 20 letras, `origem = sem_fala` e `transcricao.txt` fica vazio.

No Windows, as DLLs de cuBLAS/cuDNN dos pacotes `nvidia-*-cu12` são registradas com `os.add_dll_directory` antes de carregar o CTranslate2.

### `transcricao.json`

```json
{
  "origem": "legenda_auto",
  "idioma": "pt",
  "caracteres": 41230,
  "palavras": 7120,
  "modelo": null,
  "legenda_erro": null,
  "transcrito_em": "2026-11-05T21:00:00+00:00"
}
```

`origem`: `legenda_manual`, `legenda_auto`, `whisper` ou `sem_fala`. `legenda_erro` explica por que a legenda não foi usada quando o Whisper entrou por falha (ex.: HTTP 429).

## Fase 3 — Análise

1. **Prompt** (`analise.base.montar_prompt`): template `prompts/analise.md` + tipo do vídeo + título/descrição + transcrição + camada `analise` do preset. Transcrições acima de `max_caracteres_transcricao` viram três blocos (início, meio e fim) separados por `[...]`. Sem fala: o prompt diz para usar título e descrição.
2. **Backend**: recebe o prompt e o JSON Schema da resposta e devolve texto. O padrão, `ClaudeCodeBackend`, executa `claude -p --output-format json --no-session-persistence --tools "" --json-schema <esquema>` numa pasta temporária, com o prompt pela entrada padrão, e lê `structured_output` (ou `result`).
3. **Validação** (`validar`): pydantic (campos obrigatórios, `posicao_texto` ∈ esquerda/direita/topo/centro) + regra do preset (`titulo_palavras`). Inválido → nova chamada com o motivo anexado ao prompt, até `tentativas` vezes a mais.
4. **Erros**: falha de backend (`ErroBackend`: sem `claude`, sem login, tempo esgotado) interrompe o lote; resposta inválida fica como erro do vídeo no estado.

### Backends futuros

Implemente `BackendAnalise` (atributo `nome` e método `gerar(prompt, esquema) -> str`) e registre em `analise.criar_backend`. Exemplos naturais: API da Anthropic (SDK `anthropic`) ou Ollama local, para quem não usa o Claude Code.

### `analise.json`

```json
{
  "tema": "perdão",
  "resumo": "2-3 frases",
  "gancho": "perdoar liberta quem perdoa",
  "emocao": "paz",
  "elementos_visuais": ["amanhecer", "lago calmo"],
  "titulo_capa": "O perdão liberta",
  "prompt_imagem": "a calm lake at sunrise ...",
  "posicao_texto": "esquerda",
  "backend": "claude_code",
  "tentativas": 1,
  "analisado_em": "2026-11-05T22:00:00+00:00"
}
```

## Fase 4 — Geração da imagem

1. **Parâmetros** (`imagem.montar_parametros`): `prompt` = cena da análise; `prompt_2` = `estilo_sufixo` + cena; `negative_prompt` do preset nos dois codificadores; `guidance_scale` e `passos` do preset; resolução nativa do tipo (`formatos.<tipo>.geracao`).
2. **Pipeline** (`GeradorSDXL`): `StableDiffusionXLPipeline` fp16 (`variant="fp16"`, `low_cpu_mem_usage`), carregado uma vez por execução, no primeiro vídeo. Com `gpu.texto_sdxl` diferente de `gpu.imagem` (padrão com duas GPUs), o trabalho é dividido:
   - `encode_prompt` na GPU de texto (codificadores CLIP-L e OpenCLIP-bigG); os embeddings vão para a GPU de imagem;
   - difusão num segundo pipeline só com o UNet e o scheduler (`output_type="latent"`) na GPU de imagem;
   - decodificação dos latentes pelo VAE em **fp32** (o VAE do SDXL gera NaN/preto em fp16), com tiling, na GPU de texto; depois `image_processor.postprocess`.

   Com `cpu_offload`, `enable_model_cpu_offload(gpu_id=gpu.imagem)` move cada componente para a GPU só enquanto ele trabalha (modo recomendado com uma GPU só). Numa GPU só sem `cpu_offload`, o pipeline inteiro roda em `cuda:<gpu.imagem>` e transborda para a RAM compartilhada. `attention_slicing` é opcional e desliga o SDPA — em testes provocou `CUBLAS_STATUS_INTERNAL_ERROR`, por isso fica desligado por padrão.
3. **Variações**: uma seed aleatória por variação (`torch.Generator` na GPU), salvas em `imagens.json` e no estado.
4. **Ajuste** (`ajustar`): escala para cobrir a saída (`formatos.<tipo>.saida`) e recorte central — 1344×768 → 1280×720; 768×1344 → 1080×1920.

Falhas (inclusive falta de VRAM) ficam no estado do vídeo e o lote continua.

### `imagens.json`

```json
{
  "modelo": "stabilityai/stable-diffusion-xl-base-1.0",
  "prompt": "An old rustic wooden farm gate ...",
  "prompt_2": "soft natural light, serene, ..., An old rustic wooden farm gate ...",
  "negative_prompt": "text, letters, words, ...",
  "largura": 1344,
  "altura": 768,
  "passos": 30,
  "guidance_scale": 6.0,
  "seeds": [123456, 789012, 345678],
  "arquivos": ["base_1.png", "base_2.png", "base_3.png"],
  "saida": [1280, 720],
  "segundos": 95.2,
  "gerado_em": "2026-11-05T23:00:00+00:00"
}
```

## Fase 5 — Composição do título

Para cada `base_N.png` (`composicao.compor_capa`):

1. **Região** (`regiao_texto`): a `posicao_texto` da análise escolhe um retângulo dentro de `layouts.<tipo>.area_segura` e o alinhamento (ver [presets.md](presets.md#camada-de-tipografia)).
2. **Tamanho** (`ajustar_texto`): da maior fonte para a menor, de 2 em 2 px, a primeira em que o título cabe na região com até `linhas_max` linhas; a quebra (`quebrar`) testa todas as divisões e fica com a de linha mais longa mais curta. O título é normalizado (NFC, espaços simples).
3. **Cor**: a de `cor_escura`/`cor_clara` com maior contraste WCAG contra a cor média do fundo atrás do bloco de texto.
4. **Véu**: retângulo arredondado em volta do texto (encostado na borda do lado do título), desfocado (`gradiente`), na cor do véu; a opacidade sobe de 0,1 em 0,1 até o contraste chegar a 3:1 (máx. 0,85).
5. **Sombra** e texto; **JPEG** com qualidade 90, baixando de 5 em 5 até caber em 2 MB (`salvar_jpeg`); miniatura de verificação.

Idempotente: um vídeo é pulado se `capas.json` e todos os arquivos existirem e `capas.json` for mais novo que `imagens.json`.

### `capas.json`

```json
{
  "titulo": "A felicidade mora dentro",
  "posicao": "esquerda",
  "tipo": "longo",
  "fonte": "Newsreader-Light.ttf",
  "capas": [
    {
      "arquivo": "capa_1.jpg",
      "miniatura": "mini_1.jpg",
      "base": "base_1.png",
      "tamanho_fonte": 115,
      "linhas": ["A felicidade", "mora dentro"],
      "cor": "#4A3F35",
      "contraste": 6.69,
      "opacidade_veu": 0.45,
      "qualidade": 90,
      "bytes": 149504,
      "avisos": []
    }
  ],
  "composto_em": "2026-11-07T22:30:00+00:00"
}
```

## Fase 6 — Revisão

- **Backup** (`baixar_original`): tenta, nesta ordem, a `thumbnail_url` do `meta.json` e `i.ytimg.com/vi/<id>/{maxresdefault,hq720,sddefault,hqdefault}.jpg`; descarta o "sem capa" do YouTube (120×90) e converte WebP/PNG para JPEG. Grava `capa_original.jpg` de forma atômica e **nunca** o sobrescreve; a URL usada fica em `dados.capa_original_url`. O `compor` apaga só as variações (`capa_N.jpg`, `mini_N.jpg`), nunca o backup. Num Short, essas imagens são horizontais: o YouTube centraliza a capa vertical e desfoca as laterais.
- **Página** (`preparar_revisao` / `montar_html`): HTML estático em `saida/<job>/revisao.html`, CSS embutido (claro/escuro), imagens por caminho relativo (`<video_id>/capa_N.jpg`), textos escapados. Inclui só os vídeos com status `capas_compostas` (com `--historico`, também os posteriores; pendentes primeiro).
- **Servidor** (`servidor.py`, `revisar --servir`): `http.server` só em 127.0.0.1, um pedido por vez. GET serve a página (com um token aleatório injetado num `<meta>`) e as imagens `.jpg`/`.png` das pastas dos jobs; POST `/api/aprovar`, `/api/rejeitar`, `/api/aprovar-todos`, `/api/ignorar` e `/api/incluir` exigem o token no cabeçalho `X-Token` e o `Host` local, chamam as mesmas funções `aprovar`/`rejeitar` e regravam a página. Sem `--servir`, o JavaScript da página não acha o token e mostra os comandos para copiar.
- **Decisão** (`aprovar` / `rejeitar`): `aprovado` grava `dados.variacao`, `dados.capa` e `dados.decidido_em`; `rejeitado` limpa a variação. `aprovado` e `rejeitado` têm a mesma ordem, então trocar entre eles não é "regredir"; sair de `enviado`/`nao_elegivel` exige `--forcar`.

## Fase 7 — Autenticação e envio

- **OAuth** (`autenticar_navegador`): `InstalledAppFlow` com `secrets/client_secret.json` e os escopos `youtube.upload` + `youtube.readonly`, servidor local numa porta livre. `canal_do_token` (`channels.list mine=true`) identifica o canal; o token vai para `secrets/tokens/<channel_id>.json` (gravação atômica). `carregar_credenciais` renova o token; `invalid_grant` vira uma mensagem pedindo `auth` de novo.
- **Envio** (`enviar_job`): só status `aprovado`; confere o canal (`meta.json`, ou `videos.list` se faltar), exige `capa_original.jpg`, trata Shorts (`nao_elegivel`), checa o limite de 2 MB, e chama `thumbnails.set` com retentativa exponencial (30 s, 60 s, 120 s) em 429/5xx e pausa aleatória de `envio.pausa_segundos` (30–60 s) entre vídeos. `quotaExceeded` para o lote. Cada vídeo enviado grava `envio.json` e passa a `enviado`.
- **Restauração** (`restaurar_video`): envia `capa_original.jpg`, acrescenta ao histórico de `envio.json` e marca `rejeitado` (com `restaurado_em`). Em Shorts, envia `capa_original_vertical.jpg` (`backup_vertical`, criado uma vez): recorta a faixa central do backup na proporção do vídeo e compara (18×32 em tons de cinza, limiar 12) com `oardefault.jpg`, o quadro vertical do vídeo, que não muda quando o Short ganha capa. Iguais: usa o quadro, em resolução cheia. Diferentes (havia capa personalizada) ou sem quadro (404): usa o recorte ampliado para 1920 px de altura. `envio.json` guarda `arquivo` e `origem`.
- A API fica atrás do protocolo `ApiCapas`, simulado nos testes.

### `envio.json`

```json
{
  "acao": "enviar",
  "enviado_em": "2026-11-16T14:00:00+00:00",
  "variacao": 2,
  "arquivo": "capa_2.jpg",
  "channel_id": "UC...",
  "resposta": {"kind": "youtube#thumbnailSetResponse", "items": [...]},
  "historico": [ { "acao": "enviar", "...": "..." } ]
}
```

## Fase 8 — Orquestração

`yt-thumbnail tudo` chama os próprios comandos da CLI em sequência (`listar`, `transcrever`, `analisar`, `gerar`, `compor`, `revisar`), com os mesmos filtros (`--job`, `--tipo`, `--limite`). Como cada etapa é idempotente e o estado só avança, a orquestração não precisa de filas: a "fila" de cada etapa é a lista de vídeos no status anterior, na ordem de `Estado.listar` (data de publicação mais recente primeiro, gravada pelo `listar` em `dados.data_publicacao`; os `ignorado` ficam de fora). Por isso o `--limite` sempre pega os vídeos mais novos.

- **Erros**: um `typer.Exit(1)` de uma etapa (vídeos com erro) é anotado e o fluxo segue; `Exit(2)` (uso/configuração) para tudo. Exceções inesperadas também não perdem o log.
- **Memória**: depois de cada etapa, `gc.collect()` e `torch.cuda.empty_cache()` (`liberar_memoria`). Whisper e SDXL nunca ficam carregados juntos.
- **Sem paralelismo**: o plano previa workers de transcrição (GPU 0) e imagem (GPU 1) em paralelo; no PC de referência (8 GB de RAM, e a GPU 1 fora de serviço) isso estoura a memória, então as etapas são sequenciais. Com 16–32 GB de RAM e as duas GPUs, dá para rodar `transcrever` e `gerar` em dois terminais ao mesmo tempo, cada um na sua GPU — o estado em SQLite aguenta.
- **Log**: o console do rich grava tudo (`record=True`) e o texto vai para `saida/logs/tudo-*.log` no fim, mesmo em caso de erro.
- **Resumo** (`resumir`): contagem por status, erros pendentes (`erro`/`mensagem` do estado) e não elegíveis, por job.
