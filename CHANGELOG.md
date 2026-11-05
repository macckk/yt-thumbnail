# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Fase 3 — Análise e prompt (Claude) ✅ (concluída em 2026-11-05)
- `analise/base.py`: interface `BackendAnalise`, montagem do prompt (template + preset + tipo), transcrição longa reduzida a início/meio/fim, extração e validação do JSON (esquema + tamanho do título do preset) com novas tentativas explicando o erro.
- `analise/claude_code.py`: backend padrão com `claude -p --output-format json`, saída estruturada (`--json-schema`), sem ferramentas e sem gravar sessão; mensagens acionáveis para falta de login (inclusive por SSH).
- Template `prompts/analise.md` reescrito (regras de prompt de imagem, símbolos neutros, área para o título, Shorts no terço central).
- Comando `yt-thumbnail analisar [--job] [--ids] [--tipo] [--forcar] [--limite]`.
- Novas chaves em `analise`: `modelo`, `timeout_segundos`, `saida_estruturada`, `template`.
- Template pede cenas tiradas do conteúdo de cada vídeo (objetos, metáforas, histórias citadas), variedade de enquadramento/ambiente/luz e figura humana só quando essencial; títulos com maiúscula só no início. Preset `espiritualidade` com repertório visual mais amplo.
- Validado no PC das GPUs com 6 vídeos reais (4 palestras + 2 Shorts): todas as respostas válidas na 1ª tentativa (~10 s por vídeo); títulos revisados quanto ao tom do preset; cenas ajustadas para mais variedade a pedido do autor.

### Fase 2 — Transcrição ✅ (concluída em 2026-11-05)
- `transcricao.py`: legenda do YouTube via yt-dlp (manual > automática), limpeza de VTT (timestamps, tags, linhas repetidas, `[Música]`), fallback com áudio + faster-whisper na GPU de transcrição, `sem_fala` para vídeos sem fala.
- Se o YouTube bloquear a legenda (HTTP 429), a transcrição segue pelo Whisper e registra `legenda_erro`.
- yt-dlp com `curl-cffi` (impersonation, exigida pelo YouTube para legendas) e `deno` (runtime JavaScript).
- DLLs de cuBLAS/cuDNN dos pacotes `nvidia-*-cu12` registradas automaticamente no Windows.
- Comando `yt-thumbnail transcrever [--job] [--ids] [--tipo] [--forcar] [--forcar-whisper] [--limite]`.
- Novas chaves em `transcricao`: `idioma_whisper`, `manter_audio`, `whisper_se_legenda_falhar`, `pausa_legendas_segundos`; `idiomas` padrão agora `["pt", "pt-BR", "pt.*"]`.
- Logger do yt-dlp silenciado (erros chegam pelas exceções, sem poluir o terminal).
- Áudio decodificado pelo FFmpeg antes do Whisper (o faster-whisper 1.2.1 é incompatível com o PyAV 19).
- Validado no PC das GPUs: palestra de 38 min pelo Whisper large-v3 na GPU 0 (legenda bloqueada por HTTP 429 → fallback; 5.394 palavras em ~6,5 min com download e carga do modelo) e 2 Shorts pela legenda automática (20 s). O caso `sem_fala` está coberto por teste automatizado.

### Fase 1 — Listagem da playlist e detecção de tipo ✅ (concluída em 2026-11-05)
- `estado.py`: estado por vídeo em SQLite (`saida/estado.db`), status só avança, erros com contagem de tentativas.
- `playlist.py`: listagem com yt-dlp (`extract_flat`), metadados completos sem baixar mídia, detecção longo/Short (≤ 180 s e vertical) com fallback pela URL `/shorts/`, `meta.json` por vídeo, conferência do `channel_id`.
- Comando `yt-thumbnail listar [--job] [--ids] [--forcar]`.
- Nova chave `ytdlp.cookies_navegador`.
- Docs: `uso-cli.md`, `configuracao.md`, `arquitetura.md` (novo), solução de problemas do yt-dlp.
- Validado no PC das GPUs com duas playlists reais: 100 Shorts (360×640 a 1080×1920, 0:17 a 2:59) e 241 vídeos longos (1920×1080), todos com o tipo correto, sem erros; a reexecução não duplica (~2 s por vídeo na 1ª vez, segundos na 2ª).

### Fase 0 — Ambiente, esqueleto e verificação ✅ (concluída em 2026-11-05)
- Estrutura do projeto, `pyproject.toml` (pacote `yt_thumbnail`, comando `yt-thumbnail`, licença GPL-3.0-or-later).
- Dependências base e extras `[gpu]` e `[dev]`.
- `config.py`: carga e validação do `config.yaml` com pydantic (jobs, canais, formatos, GPUs, referências cruzadas).
- `presets.py` e o primeiro preset, `presets/espiritualidade.yaml`.
- Template `prompts/analise.md`.
- Comandos `yt-thumbnail ambiente` e `yt-thumbnail validar`; `scripts/check_env.py`.
- `scripts/baixar_fontes.py` (fontes OFL do Google Fonts).
- CI no GitHub Actions (ruff + pytest, sem GPU).
- Documentação: README, instalação no Windows, configuração, presets, uso da CLI, solução de problemas.
- Docs: execução em outro PC por SSH e token do Claude Code para modo headless remoto.
- `yt-thumbnail ambiente` escapa marcação do rich (as dicas com `[gpu]` apareciam cortadas).
- Validado no PC das GPUs: Python 3.12, torch 2.11+cu128, 2× RTX 3060 Ti, todos os itens OK; CI verde.
