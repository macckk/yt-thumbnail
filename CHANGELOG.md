# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

## [0.1.0] — 2026-11-16

Primeira versão: da playlist do YouTube até a capa enviada, com revisão humana no meio.

### Fase 9 — Preparação para o GitHub ✅ (concluída em 2026-11-16)
- README final: exemplos de antes × depois (longos e Shorts), requisitos de hardware, início rápido em 5 passos, fluxo do dia a dia e limitações conhecidas (login de 7 dias, cota, Shorts, HTTP 429, acentos sem `libraqm`, Claude Code por SSH).
- Shorts: `shorts_capa_personalizada` passa a ser `true` por padrão (os canais aceitam capa personalizada em Shorts); 403 da API continua virando `nao_elegivel`.
- `config.example.yaml` pronto para **uma GPU** (`gpu.imagem: 0`, `imagem.cpu_offload: true`); `yt-thumbnail ambiente` aceita 1 GPU (2 é a recomendação).
- `fonttools` virou dependência (o `baixar_fontes.py` falhava numa instalação nova sem ele).
- Templates de issue (problema, ideia/preset) e de PR em `.github/`; vulnerabilidades vão para o aviso privado.
- Varredura de segredos: `gitleaks` no histórico inteiro (sem vazamentos) e job `segredos` no CI; `config.yaml`, `secrets/`, `saida/`, tokens e `client_secret` nunca foram commitados.
- `THIRD_PARTY_NOTICES.md` completo (NumPy, fontTools, curl-cffi, deno).
- Instalação limpa validada no PC das GPUs, numa pasta nova e seguindo só a documentação: clone, PyTorch cu128, extras, bibliotecas CUDA, fontes, `validar` e `ambiente` todos OK com 1 GPU, testes verdes (8 min 39 s). Depois, `tudo --job meditacoes --limite 1` levou um vídeo da playlist até a revisão em 11 min (69 s por imagem), com 3 capas e o backup da capa atual.
- `README.en.md` (opcional no plano) ficou para depois.

### Fase 8 — Orquestração ✅ (concluída em 2026-11-16)
- `orquestracao.py` e comando `yt-thumbnail tudo [--job] [--tipo] [--limite] [--ate ETAPA] [--abrir]`: listar → transcrever → analisar → gerar → compor → revisar, parando na revisão (envio sempre explícito); erro de um vídeo ou de uma etapa não para o fluxo; memória da GPU liberada entre etapas; resumo final por etapa (tempo) e por job (na revisão, pendentes, aprovados, enviados, não elegíveis, erros); log em `saida/logs/tudo-*.log`.
- Etapas em sequência, sem workers paralelos: com 8 GB de RAM, Whisper e SDXL juntos não cabem (documentado em `arquitetura.md`).
- `listar --so-novos` (usado pelo `tudo`) para não repetir a tabela inteira da playlist.
- Docs: `tudo` em `uso-cli.md` (inclusive agendamento no Windows), "Fluxo do dia a dia" no README, seção da Fase 8 em `arquitetura.md`.
- Validado no PC das GPUs (1 GPU, 8 GB de RAM): `tudo --limite 2` levou 4 vídeos novos (2 por job) da playlist à revisão em 32 min (transcrição 15 min pelo Whisper por causa do HTTP 429 nas legendas, imagens 15 min a ~75 s cada), pulando o que já existia; pico de 5,7 GB no processo e a RAM livre do sistema chegou a ~4 MB (sem travar).

### Fase 7 — Autenticação multicanal e envio ✅ (concluída em 2026-11-16)
- `youtube_api.py`: OAuth "App para computador" com `youtube.upload` + `youtube.readonly`, um token por canal em `secrets/tokens/<channel_id>.json`, renovação automática e aviso de login vencido (modo Teste: 7 dias).
- Envio só de aprovados, conferindo o canal do vídeo e exigindo o backup da capa atual; Shorts de canais sem capa própria viram `nao_elegivel`; pausa aleatória entre envios, novas tentativas em 429/5xx, cota esgotada para o lote; `envio.json` com histórico.
- Comandos `auth --canal`, `canais`, `enviar --aprovados [--dry-run]`, `restaurar ID`; `auth` preenche o `channel_id` vazio no `config.yaml`.
- Docs: `google-oauth.md` (Google Cloud passo a passo, login, Teste × Produção, cota) e `shorts.md`.
- Validado com o canal real: login OAuth no PC das GPUs (channel_id preenchido sozinho; os 341 vídeos das playlists são do canal), `--dry-run` mostrando só o aprovado e primeiro envio real (`5by3mocX5_E`, variação 1) confirmado no YouTube. `restaurar` e o caso dos Shorts `nao_elegivel` validados por testes automatizados (o autor optou por não reverter a capa enviada).

### Fase 6 — Revisão (HTML) ✅ (concluída em 2026-11-07)
- `revisao.py`: backup da capa atual em `capa_original.jpg` (baixado uma única vez, nunca sobrescrito; ignora o "sem capa" 120×90 do YouTube e converte WebP), página estática `saida/<job>/revisao.html` com selo LONGO/SHORT, capa atual, variações em tamanho real e miniatura, métricas da composição e comandos prontos para copiar.
- Comandos `yt-thumbnail revisar [--job] [--tipo] [--nao-abrir] [--offline]`, `aprovar ID... --variacao N`, `aprovar --todos --variacao N`, `rejeitar ID...`; mudar a decisão de vídeo já enviado só com `--forcar`.
- Docs: fluxo de revisão em `uso-cli.md` com captura de tela (`docs/img/revisao.jpg`).
- Validado no PC das GPUs: 6 capas atuais baixadas (backup) e páginas dos dois jobs geradas; aprovar, rejeitar, `--todos` e mudança de decisão cobertos por testes e conferidos numa cópia dos dados reais.

### Fase 5 — Composição do título (Pillow) ✅ (concluída em 2026-11-07)
- `composicao.py`: região do título pela `posicao_texto` dentro da área segura (longo evita o canto inferior direito; Short no quadrado central, acima do assunto), maior fonte que cabe em até `linhas_max` linhas com quebra equilibrada, cor escura ou clara pelo contraste WCAG, véu translúcido que sobe até o contraste chegar a 3:1, sombra suave.
- JPEG < 2 MB (qualidade 90, baixando se precisar), miniatura de verificação 320×180 / 180×320 e `capas.json` com tamanho da fonte, contraste e avisos.
- Comando `yt-thumbnail compor [--job] [--ids] [--tipo] [--forcar] [--limite]`.
- Preset `espiritualidade`: fonte principal **Newsreader Light** (tamanho óptico de título) no lugar da Cormorant Garamond, que desenha os acentos deslocados no Pillow sem `libraqm` (Windows); área segura do longo simétrica e a do Short no quadrado central.
- `scripts/baixar_fontes.py` instancia também o eixo de tamanho óptico; fontes baixadas ficam fora do git.
- Validado no PC das GPUs: 18 capas (4 palestras + 2 Shorts, 3 variações cada) em 4 s, de 110 a 225 KB, contraste entre 5,3:1 e 7,5:1, sem avisos; legíveis nas miniaturas.

### Fase 4 — Geração da imagem (SDXL) ✅ (concluída em 2026-11-07)
- `imagem.py`: SDXL 1.0 base fp16 na GPU de imagem, carregado uma vez por execução, VAE tiling; `attention_slicing` e `cpu_offload` opcionais.
- Prompt dividido entre os dois codificadores do SDXL (cena no 1º; estilo do preset + cena no 2º) para não cortar nada no limite de 77 tokens.
- Variações com seeds aleatórias salvas em `imagens.json` e no estado; ajuste por escala + recorte central para a saída (1280×720 / 1080×1920).
- Comando `yt-thumbnail gerar [--job] [--ids] [--tipo] [--variacoes] [--forcar] [--limite]`.
- Novas chaves `imagem.attention_slicing` e `imagem.cpu_offload`.
- SDXL dividido entre as duas GPUs de 8 GB: UNet na GPU `imagem`; codificadores de texto e VAE (fp32) na nova `gpu.texto_sdxl` (padrão: a de transcrição).
- VAE tiling compatível com diffusers 0.42 (`pipe.vae.enable_tiling`).
- Template de análise pede que o `prompt_imagem` comece pela composição (o fim pode ser cortado no limite de 77 tokens).
- Validado no PC das GPUs (2× RTX 3060 Ti, 8 GB de RAM): ~52 s por imagem em 1344×768, pico de VRAM ~6,1 GB (UNet) e ~8 GB (codificadores + VAE), pico de RAM do processo 4,7 GB; imagens sem texto, claras e serenas (longo e Short). Problema de hardware: a GPU 1 cai do barramento PCIe sob carga contínua (erros WHEA no root port), a investigar no hardware. Com uma GPU só (todas as chaves de `gpu` em `0`) a geração funciona, com `imagem.cpu_offload: true` a ~81 s por imagem (sem ele, 5 a 11 min, porque a VRAM transborda para a RAM do sistema). Aceite fechado assim: 6 vídeos reais (4 palestras + 2 Shorts), 3 variações cada, sem texto e sem erros.

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
