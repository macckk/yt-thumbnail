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
```

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
| `ambiente.py` | verificação do ambiente |
| `cli.py` | comandos (Typer) |

## Fase 1 — Listagem e detecção de tipo

1. `yt-dlp` com `extract_flat` lista os IDs da playlist (equivale a `yt-dlp --flat-playlist -J`).
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

- **Backup** (`baixar_original`): tenta, nesta ordem, a `thumbnail_url` do `meta.json` e `i.ytimg.com/vi/<id>/{maxresdefault,hq720,sddefault,hqdefault}.jpg`; descarta o "sem capa" do YouTube (120×90) e converte WebP/PNG para JPEG. Grava `capa_original.jpg` de forma atômica e **nunca** o sobrescreve; a URL usada fica em `dados.capa_original_url`.
- **Página** (`preparar_revisao` / `montar_html`): HTML estático em `saida/<job>/revisao.html`, CSS embutido (claro/escuro), imagens por caminho relativo (`<video_id>/capa_N.jpg`), textos escapados. Inclui vídeos com status `capas_compostas` ou posterior; pendentes primeiro.
- **Decisão** (`aprovar` / `rejeitar`): `aprovado` grava `dados.variacao`, `dados.capa` e `dados.decidido_em`; `rejeitado` limpa a variação. `aprovado` e `rejeitado` têm a mesma ordem, então trocar entre eles não é "regredir"; sair de `enviado`/`nao_elegivel` exige `--forcar`.
