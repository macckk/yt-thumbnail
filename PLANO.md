# Plano de trabalho — yt-thumbnail

**yt-thumbnail** — gerador automático de capas para playlists do YouTube. Licença: **GNU GPL v3.0**.

> Documento para orientar o desenvolvimento no Claude Code.
> Coloque este arquivo na raiz do repositório e peça ao Claude Code para executar **uma fase por vez**, validando o critério de aceite antes de seguir.
> O projeto será publicado no GitHub: **documentação faz parte da definição de pronto de cada fase** (ver seção 7).

---

## 1. Objetivo

A partir de uma **playlist pública** de um dos canais do usuário, para cada vídeo (**longo ou Short**):

1. obter a transcrição;
2. analisar o conteúdo e gerar um **prompt de imagem** e um **título curto de capa**, de acordo com um **preset** de identidade visual;
3. gerar a imagem **localmente** (sem texto), no formato certo para vídeo longo ou Short;
4. escrever o título sobre a imagem com Pillow, seguindo o preset;
5. permitir **revisão humana** em HTML (antes × depois);
6. enviar a capa aprovada ao YouTube via API, no canal correto.

Tudo gratuito, rodando num PC Windows local.

## 2. Decisões tomadas

| Tema | Decisão |
|---|---|
| Ambiente | PC local Windows, Python, 2× GPU NVIDIA de 8 GB |
| Canais | **Vários canais, todos próprios** → suporte multicanal (um token OAuth por canal) |
| Tipos de vídeo | **Vídeos longos e Shorts**, com layouts e tamanhos diferentes; envio de capa de Short só para canais elegíveis (ver seção 3) |
| Listagem da playlist | `yt-dlp` (playlist pública: sem API key) |
| Transcrição | 1º legenda do YouTube via `yt-dlp`; fallback `faster-whisper` na **GPU 0** |
| Análise e prompt | Claude Code headless (`claude -p`) como backend padrão, atrás de uma interface plugável |
| Geração de imagem | **SDXL 1.0 base** local via `diffusers` na **GPU 1** |
| Identidade visual | Sistema de **presets** em YAML; primeiro preset: **Espiritualidade** |
| Variações | **3** por vídeo |
| Texto na capa | Imagem gerada **sem texto**; título aplicado com Pillow |
| Revisão | **HTML estático** + aprovação pela CLI |
| Envio | YouTube Data API v3, `thumbnails.set`, OAuth "Desktop app" |
| Segurança | Backup da capa original + revisão obrigatória + `--dry-run` |
| Nome | **yt-thumbnail** (repositório, pacote `yt_thumbnail`, comando `yt-thumbnail`) |
| Licença | **GNU GPL v3.0** (`GPL-3.0-or-later`) |
| Publicação | Repositório público no GitHub com documentação completa |

## 3. Vídeos longos × Shorts

| Item | Vídeo longo | Short |
|---|---|---|
| Detecção | duração > 180 s e formato horizontal | duração ≤ 180 s **e** formato vertical (largura/altura via metadados do `yt-dlp`) |
| Geração SDXL (nativa) | 1344×768 | 768×1344 |
| Saída final | 1280×720 (16:9) | configurável; padrão 1080×1920 (9:16) |
| Área segura do título | evitar canto inferior direito (selo de duração) | manter título e assunto **no terço central** (o YouTube recorta a capa do Short em algumas telas) |
| Envio | `thumbnails.set` | só se o canal for elegível (`shorts_capa_personalizada: true`); senão a capa fica salva, sem envio |

**Atenção — capas personalizadas em Shorts são restritas.** O YouTube começou a liberar capa personalizada para Shorts em **julho de 2026**, **só para canais do Programa de Parcerias (YPP)**, **só pelo desktop**, e a capa é exibida recortada em algumas superfícies.

**Situação atual dos canais do autor: nenhum está no YPP** → hoje não é possível definir capa personalizada em Shorts nesses canais (nem pela API, nem pelo Studio). Decisões:
- **Detecção de Shorts é obrigatória** desde a Fase 1: mesmo sem enviar capa, o fluxo precisa saber o tipo para não tratar Short como vídeo longo.
- Configuração por canal `shorts_capa_personalizada: false` (padrão). Com `false`, as capas de Shorts **podem ser geradas** (útil para o futuro ou para outras redes), mas o envio é pulado e o estado vira `nao_elegivel`.
- A config permite `tipos: [longo]` ou `tipos: [longo, short]` por job; o `config.example.yaml` vem com **`tipos: [longo]`**, e gerar capa de Short é opcional.
- O envio de Short pela API fica implementado atrás da flag, mas **não testado** com canal real; `docs/shorts.md` deixa isso explícito e convida contribuições de quem tiver canal no YPP.
- O formato de saída do Short fica **configurável** (`formatos.short.saida`).

## 4. Multicanal

- **Um** OAuth client (`client_secret.json`) para o projeto; **um token por canal** em `secrets/tokens/<channel_id>.json`.
- Comando `yt-thumbnail auth --canal <apelido>`: abre o navegador; na tela do Google, escolher o canal (contas de marca aparecem como opções). O script confirma com `channels.list(mine=true)` e grava o token com o `channel_id` real.
- Na config, cada **job** associa playlist → canal → preset:
  ```yaml
  jobs:
    - nome: meditacoes
      playlist: https://www.youtube.com/playlist?list=XXXX
      canal: espiritual-principal      # apelido definido em `canais`
      preset: espiritualidade
      tipos: [longo]                   # adicionar `short` para também gerar capas de Shorts
  canais:
    espiritual-principal:
      channel_id: UCxxxx               # preenchido pelo `yt-thumbnail auth`
      shorts_capa_personalizada: false # true só para canais no Programa de Parcerias
  ```
- No envio, conferir que o `channel_id` do vídeo é o do token usado; se não bater, pular e avisar (protege contra job configurado com o canal errado).
- `yt-thumbnail canais`: lista os canais autenticados e a validade de cada token.

## 5. Preset "Espiritualidade"

Presets ficam em `presets/<nome>.yaml` e controlam **três camadas**: o tom da análise (Claude), o estilo da imagem (SDXL) e a tipografia (Pillow). Novos presets se criam copiando um arquivo existente.

**Diretrizes do preset `espiritualidade`:**

- **Tom (análise/título):** acolhedor, sereno, esperançoso; títulos curtos e gentis (2 a 5 palavras); **sem sensacionalismo, sem medo, sem promessas milagrosas**; segunda pessoa afetuosa permitida ("Você não está só").
- **Imagem:**
  - luz natural suave, amanhecer/golden hour, raios de luz, névoa leve, céu aberto, água calma, natureza (campos, montanhas ao longe, flores, folhas), velas, mãos em gesto de cuidado;
  - paleta clara: creme, marfim, dourado suave, azul-céu, verde-sálvia, rosa pálido; alta luminosidade e baixo contraste;
  - pessoas preferencialmente **de costas, em silhueta ou à distância** (o SDXL base erra em rostos e mãos de perto);
  - **símbolos religiosos sempre neutros** (`simbolos: neutro`; a chave existe no preset para quem quiser criar outro preset no futuro);
  - `estilo_sufixo` (exemplo): `soft natural light, serene, peaceful atmosphere, pastel tones, airy, gentle glow, high key, dreamy, cinematic composition, empty space for text`;
  - `negative_prompt` (exemplo): `text, letters, words, watermark, logo, dark, gloomy, horror, blood, violence, harsh shadows, oversaturated, neon, cluttered, deformed hands, distorted face`.
- **Tipografia:**
  - fontes finas e delicadas, livres (licença OFL, Google Fonts): **Cormorant Garamond Light/Regular** (principal), **Raleway Light** ou **Josefin Sans Light** (alternativas);
  - usar peso **Light (300)**, não Thin (100): fonte muito fina some quando a capa aparece pequena;
  - cor do texto escura e quente sobre fundo claro (ex.: `#4A3F35`) ou branco com brilho suave sobre áreas mais escuras — escolha automática pelo brilho médio da região do texto;
  - legibilidade: véu/gradiente translúcido claro atrás do texto, sombra suave (blur) em vez de contorno grosso, tamanho de fonte generoso;
  - alinhamento centralizado ou à esquerda, conforme `posicao_texto`.
- **Teste de legibilidade obrigatório:** cada capa é verificada também reduzida (320×180 para longo; 180×320 para Short).

Estrutura do arquivo de preset:
```yaml
nome: espiritualidade
descricao: Imagens claras, serenas e acolhedoras; tipografia fina e delicada
analise:
  tom: "acolhedor, sereno, esperançoso, sem sensacionalismo"
  titulo_palavras: [2, 5]
  proibido: ["promessas milagrosas", "medo", "urgência artificial"]
imagem:
  estilo_sufixo: "..."
  negative_prompt: "..."
  paleta: ["#FFF8EC", "#F3E3C3", "#D8B46A", "#BFD7EA", "#B7C9A8"]
  simbolos: neutro
  guidance_scale: 6.0
  passos: 30
tipografia:
  fonte: assets/fonts/CormorantGaramond-Light.ttf
  fonte_alternativa: assets/fonts/Raleway-Light.ttf
  cor_escura: "#4A3F35"
  cor_clara: "#FFFFFF"
  sombra: { blur: 8, opacidade: 0.35 }
  veu: { cor: "#FFF8EC", opacidade: 0.45, tipo: gradiente }
  linhas_max: 3
layouts:
  longo: { area_segura: [0.06, 0.08, 0.80, 0.85] }
  short: { area_segura: [0.10, 0.33, 0.90, 0.66] }
```

## 6. Estrutura do projeto

```
yt-thumbnail/
├─ README.md                 # visão geral, exemplos, início rápido
├─ PLANO.md                  # este arquivo (pode ir para docs/ ao publicar)
├─ LICENSE                   # texto integral da GNU GPL v3.0
├─ THIRD_PARTY_NOTICES.md    # SDXL (OpenRAIL++-M), fontes (OFL), bibliotecas
├─ CHANGELOG.md
├─ CONTRIBUTING.md
├─ SECURITY.md               # como tratar segredos e tokens
├─ config.example.yaml       # config de exemplo (a real fica fora do git)
├─ .env.example
├─ .gitignore                # secrets/, saida/, config.yaml, .env, modelos
├─ pyproject.toml
├─ docs/
│  ├─ instalacao-windows.md
│  ├─ configuracao.md        # referência completa de config.yaml
│  ├─ presets.md             # como funcionam e como criar novos
│  ├─ google-oauth.md        # passo a passo do Google Cloud + multicanal
│  ├─ uso-cli.md             # todos os comandos e flags
│  ├─ shorts.md              # particularidades e limitações dos Shorts
│  ├─ arquitetura.md         # fluxo, estados, módulos, diagrama
│  ├─ solucao-de-problemas.md
│  └─ img/                   # capturas da revisão, exemplos de capas
├─ presets/
│  └─ espiritualidade.yaml
├─ prompts/
│  └─ analise.md             # template base; o preset injeta o tom
├─ assets/fonts/             # fontes OFL + arquivos de licença das fontes
├─ src/yt_thumbnail/
│  ├─ cli.py                 # listar, transcrever, analisar, gerar, compor, revisar, aprovar, enviar, restaurar, auth, canais, tudo
│  ├─ config.py              # carga e validação (pydantic)
│  ├─ estado.py              # status por vídeo (SQLite)
│  ├─ presets.py
│  ├─ playlist.py            # Fase 1
│  ├─ transcricao.py         # Fase 2
│  ├─ analise/
│  │  ├─ base.py             # interface do backend de análise
│  │  └─ claude_code.py      # backend padrão (claude -p)
│  ├─ imagem.py              # Fase 4
│  ├─ composicao.py          # Fase 5
│  ├─ revisao.py             # Fase 6
│  └─ youtube_api.py         # Fase 7
├─ scripts/
│  ├─ check_env.py           # Fase 0
│  └─ baixar_fontes.py       # opcional, se as fontes não forem versionadas
├─ tests/                    # pytest; sem GPU (mocks)
├─ .github/workflows/ci.yml  # lint (ruff) + testes
└─ saida/<job>/<video_id>/   # artefatos (fora do git)
   ├─ meta.json              # inclui tipo: longo | short
   ├─ legenda.vtt | audio.m4a
   ├─ transcricao.txt
   ├─ analise.json
   ├─ base_1..3.png
   ├─ capa_1..3.jpg
   ├─ capa_original.jpg
   └─ envio.json
```

## 7. Documentação e publicação (requisito transversal)

**Definição de pronto de cada fase:** código + testes + documentação atualizada (o `docs/` correspondente, `uso-cli.md` se surgiu comando novo, `configuracao.md` se surgiu chave nova, `CHANGELOG.md`).

Padrões:
- Documentação em **português** (README em inglês opcional na Fase 9: `README.en.md`).
- Docstrings em todas as funções públicas; type hints em todo o código.
- `yt-thumbnail --help` e `yt-thumbnail <comando> --help` completos (Typer).
- Mensagens de erro acionáveis: dizer **o que fazer**, com link para `solucao-de-problemas.md` quando fizer sentido.
- Nenhum dado pessoal no repositório: IDs de canal, playlists e tokens só em `config.yaml`/`secrets/`, ambos no `.gitignore`.
- Código portátil (`pathlib`, sem caminhos fixos do Windows). Windows é a plataforma suportada; Linux documentado como "deve funcionar".
- O README deixa claro que **cada pessoa cria seu próprio OAuth client** no Google Cloud (o projeto não distribui credenciais) e que **os modelos não são distribuídos** — são baixados do Hugging Face na primeira execução.

---

## 8. Estado por vídeo

```
listado → transcrito → analisado → imagens_geradas → capas_compostas → aprovado → enviado
                                                                       ↘ rejeitado
                                                            aprovado → nao_elegivel (Short em canal sem capa personalizada)
```

- Toda etapa é **idempotente**: se o artefato existe e é válido, pula.
- `--forcar` refaz uma etapa específica; `--ids` restringe a vídeos; `--tipo longo|short` filtra por tipo.
- Erros ficam registrados (`erro`, `mensagem`, `tentativas`) sem derrubar o lote.

---

## 9. Fases

### Fase 0 — Ambiente, esqueleto e verificação ✅ concluída (2026-11-05)
**Tarefas**
- `pyproject.toml` (nome `yt-thumbnail`, `license = "GPL-3.0-or-later"`, entry point `yt-thumbnail = yt_thumbnail.cli:app`), venv, estrutura de pastas, `.gitignore`, `LICENSE` (GPL v3), `README.md` inicial, `config.example.yaml`, `.env.example`.
- Dependências: PyTorch com CUDA (index-url oficial cu12x), `diffusers`, `transformers`, `accelerate`, `faster-whisper`, `yt-dlp`, `Pillow`, `google-api-python-client`, `google-auth-oauthlib`, `pydantic`, `pyyaml`, `typer`, `rich`; dev: `pytest`, `ruff`.
- Bibliotecas CUDA para o faster-whisper (cuBLAS/cuDNN CUDA 12) via pacotes `nvidia-*-cu12` ou pacote do Purfview.
- `scripts/check_env.py`: GPUs e VRAM, versão CUDA, `ffmpeg`, `yt-dlp`, `claude --version`, fontes presentes.
- `config.py` com validação (pydantic) e carregamento de presets.
- CI no GitHub Actions (ruff + pytest, sem GPU).

**Docs:** `docs/instalacao-windows.md` (passo a passo do zero, incluindo drivers e FFmpeg), esqueleto do README.
**Aceite:** `check_env.py` mostra as 2 GPUs e todos os itens OK; `yt-thumbnail --help` funciona; CI verde.

### Fase 1 — Listagem da playlist e detecção de tipo ✅ concluída (2026-11-05)
**Tarefas**
- `yt-dlp --flat-playlist -J <url>` para a lista; metadados por vídeo (duração, largura/altura, `channel_id`) com uma chamada de metadados completa do `yt-dlp`, sem baixar mídia.
- Classificar `tipo: longo | short` (regra da seção 3).
- Gravar `saida/<job>/<id>/meta.json` e registrar como `listado`.
- Comando: `yt-thumbnail listar [--job nome]`.

**Docs:** `docs/configuracao.md` (jobs, canais, tipos), `docs/uso-cli.md`.
**Aceite:** todos os vídeos aparecem com o tipo correto (testar com playlist que tenha longos e Shorts); rodar duas vezes não duplica.

### Fase 2 — Transcrição ✅ concluída (2026-11-05)
**Tarefas**
- Legenda: `yt-dlp --write-subs --write-auto-subs --sub-langs "pt.*,pt" --skip-download --sub-format vtt`; preferir manual; limpar VTT (timestamps e linhas repetidas da legenda automática).
- Fallback: baixar só o áudio (`-f bestaudio`) e transcrever com `faster-whisper` (`device="cuda"`, `device_index=0`, `compute_type="float16"`, `language="pt"`, modelo `large-v3` ou `turbo`, `vad_filter=True`).
- Shorts: mesma lógica (transcrição curta; se vazia — ex.: Short só com música — marcar `sem_fala` e seguir com título original + descrição).
- Registrar a origem: `legenda_manual | legenda_auto | whisper | sem_fala`.
- Comando: `yt-thumbnail transcrever [--forcar-whisper]`.

**Docs:** seção de transcrição em `docs/arquitetura.md`; problemas comuns (CUDA/cuDNN) em `solucao-de-problemas.md`.
**Aceite:** `transcricao.txt` para todos; vídeo sem legenda transcrito na GPU 0; Short sem fala tratado.

### Fase 3 — Análise e prompt (Claude) ✅ concluída (2026-11-05)
**Tarefas**
- Interface `analise/base.py` (entrada: meta + transcrição + preset; saída: `analise.json`). Implementar só `claude_code.py` agora; a interface permite backends futuros (API da Anthropic, Ollama) para quem for usar o projeto sem Claude Code.
- Template `prompts/analise.md` + bloco de tom vindo do preset; informar o **tipo** (longo/short) para o Claude escolher composição vertical ou horizontal.
- Chamada: `claude -p` pedindo **apenas JSON** (`--output-format json`); validar com pydantic; até 2 novas tentativas.
- Esquema de `analise.json`:
  ```json
  {
    "tema": "...",
    "resumo": "2-3 frases",
    "gancho": "...",
    "emocao": "paz | esperança | gratidão | ...",
    "elementos_visuais": ["...", "..."],
    "titulo_capa": "2 a 5 palavras, em português",
    "prompt_imagem": "em inglês, sem texto/letras, com espaço vazio para o título",
    "posicao_texto": "esquerda | direita | topo | centro"
  }
  ```
  O `estilo_sufixo` e o `negative_prompt` do preset são concatenados depois, no código (não dependem do Claude).
- Transcrições longas: truncar ou resumir em blocos antes da análise.
- Comando: `yt-thumbnail analisar`.

**Docs:** `docs/presets.md` (camada de análise), como editar o template.
**Aceite:** `analise.json` válido para todos; títulos respeitam o tom do preset (revisar 5 exemplos reais).

### Fase 4 — Geração da imagem (SDXL) ✅ concluída (2026-11-07)
**Tarefas**
- `StableDiffusionXLPipeline` fp16 na GPU 1 (`cuda:1`), modelo carregado **uma vez** por lote.
- Resolução nativa por tipo: 1344×768 (longo) / 768×1344 (Short); depois redimensionar/recortar para a saída configurada.
- Prompt final = `prompt_imagem` + `estilo_sufixo` do preset; `negative_prompt` do preset; `guidance_scale` e `passos` do preset.
- 3 variações com seeds diferentes (salvas no estado para reprodutibilidade).
- Otimizações para 8 GB: `enable_vae_tiling()`, `enable_attention_slicing()` se preciso.
- Comando: `yt-thumbnail gerar [--variacoes 3]`.

**Docs:** `docs/presets.md` (camada de imagem), requisitos de VRAM, licença do SDXL em `THIRD_PARTY_NOTICES.md`.
**Aceite:** 3 imagens sem texto por vídeo, no formato do tipo; claras e serenas conforme o preset; sem estouro de VRAM.

### Fase 5 — Composição do título (Pillow)
**Tarefas**
- Layout por tipo (área segura do preset); posição pela `posicao_texto`.
- Cor automática (escura ou clara) pelo brilho médio da região; véu translúcido + sombra suave.
- Quebra em até `linhas_max` linhas; ajuste automático do tamanho da fonte.
- Longo: evitar canto inferior direito. Short: título no terço central.
- JPEG qualidade ~90, garantindo **< 2 MB** (reduzir a qualidade em laço se passar).
- Gerar também uma miniatura de verificação (320×180 / 180×320) para a revisão.
- Comando: `yt-thumbnail compor`.

**Docs:** `docs/presets.md` (camada de tipografia, como trocar fontes), créditos das fontes.
**Aceite:** capas legíveis na miniatura; todas < 2 MB; layout de Short correto.

### Fase 6 — Revisão (HTML)
**Tarefas**
- Baixar a capa atual de cada vídeo → `capa_original.jpg` (também é o **backup**).
- Gerar `saida/<job>/revisao.html`: por vídeo, tipo (selo LONGO/SHORT), capa original, as 3 variações em tamanho real e em miniatura, título e resumo; o comando de aprovação pronto para copiar ao lado de cada variação.
- `yt-thumbnail aprovar <id> --variacao 2`, `yt-thumbnail rejeitar <id>`, `yt-thumbnail aprovar --todos --variacao 1`.
- Comando: `yt-thumbnail revisar` (gera e abre o HTML).

**Docs:** `docs/uso-cli.md` (fluxo de revisão) + captura de tela em `docs/img/`.
**Aceite:** aprovar/rejeitar funciona e o estado reflete a escolha.

### Fase 7 — Autenticação multicanal e envio
**Tarefas**
- `yt-thumbnail auth --canal <apelido>` e `yt-thumbnail canais` (seção 4).
- OAuth Desktop (`InstalledAppFlow`), escopo `youtube.upload` (ou `youtube.force-ssl`).
- Antes do envio: conferir `channel_id` do vídeo × token do job; pular se não bater.
- `thumbnails.set` só para os aprovados; pausa de 5–10 s entre envios; backoff em `429`.
- `invalid_grant` (token vence em 7 dias com o app em modo Testing): avisar e oferecer `yt-thumbnail auth` de novo. Documentar como publicar o app para eliminar o limite.
- **Shorts:** se o canal tiver `shorts_capa_personalizada: false`, pular o envio e marcar `nao_elegivel` (listar no resumo, sem tratar como erro). Se `true`, enviar normalmente; 403 em Short → `nao_elegivel` com a mensagem da API.
- `envio.json` com data, variação e resposta da API.
- Comandos: `yt-thumbnail enviar --aprovados [--dry-run] [--tipo ...]`, `yt-thumbnail restaurar <id>`.

**Docs:** `docs/google-oauth.md` (passo a passo com capturas: projeto, API, tela de consentimento, client Desktop, multicanal, modo Testing × Production, cota), `docs/shorts.md`.
**Aceite:** `--dry-run` correto; capa de vídeo longo aparece no Studio; Shorts dos canais atuais são pulados como `nao_elegivel`; `restaurar` funciona.

### Fase 8 — Orquestração e paralelismo
**Tarefas**
- `yt-thumbnail tudo [--job nome]`: listar → transcrever → analisar → gerar → compor → revisar (**para na revisão**; enviar é sempre explícito).
- Workers: transcrição (GPU 0) e imagem (GPU 1) consumindo filas em paralelo.
- Log em arquivo + resumo final (OK / pulados / erros / não elegíveis).
- Rodar todos os jobs: `yt-thumbnail tudo --todos-jobs`.

**Docs:** `docs/arquitetura.md` completo (diagrama do fluxo e dos estados), seção "fluxo do dia a dia" no README.
**Aceite:** playlist inteira (longos + Shorts) chega à revisão sem intervenção; reexecução só processa o que falta.

### Fase 9 — Preparação para o GitHub
**Tarefas**
- README final: o que é, exemplos de capas (antes × depois), requisitos de hardware, início rápido em 5 passos, links para `docs/`, limitações conhecidas (Shorts, cota, 7 dias).
- Licença GPL v3: `LICENSE` com o texto integral, `SPDX-License-Identifier: GPL-3.0-or-later` no topo de cada arquivo `.py`, seção "Licença" no README; conferir a compatibilidade das dependências (MIT/BSD/Apache-2.0 são compatíveis com GPL v3). Pesos do SDXL não são distribuídos (download pelo usuário, licença OpenRAIL++-M) e as fontes OFL vão com seus próprios arquivos de licença.
- `CONTRIBUTING.md` (como rodar testes, padrão de commits, como criar um preset; contribuições ficam sob GPL v3), `SECURITY.md`, `CHANGELOG.md` com a versão `0.1.0`, `THIRD_PARTY_NOTICES.md` revisado.
- Templates de issue e PR em `.github/`.
- Varredura de segredos no histórico (ex.: `gitleaks`) e conferência de que `config.yaml`, `secrets/` e `saida/` nunca foram commitados.
- Teste de instalação limpa: seguir `docs/instalacao-windows.md` do zero numa pasta nova (idealmente outra máquina ou usuário) e corrigir o que faltar.
- Opcional: `README.en.md`.
- Tag `v0.1.0` e release.

**Aceite:** uma pessoa que não conhece o projeto consegue instalar, configurar um canal e gerar capas só lendo a documentação.

---

## 10. Sugestão de sessões no Claude Code

| Sessão | Conteúdo |
|---|---|
| 1 | Fase 0 (esqueleto, config, presets, CI, instalação) |
| 2 | Fase 1 (listagem e detecção longo/Short) |
| 3 | Fase 2 (transcrição) |
| 4 | Fase 3 (análise; ajustar o tom do preset com 5 vídeos reais) |
| 5 | Fase 4 (SDXL; ajustar estilo do preset e VRAM) |
| 6 | Fases 5 e 6 (composição e revisão) |
| 7 | Fase 7 (multicanal, envio; teste com 1 vídeo longo) |
| 8 | Fase 8 (orquestração) |
| 9 | Fase 9 (publicação) |

No início de cada sessão: pedir ao Claude Code para ler este `PLANO.md`, o `CHANGELOG.md` e o estado do repositório. Ao fim: atualizar o `CHANGELOG.md` e marcar a fase como concluída aqui.

## 11. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| YouTube bloquear/alterar o `yt-dlp` | Manter atualizado (`-U`); suporte opcional a cookies do navegador |
| Canais fora do YPP não aceitam capa em Short | Flag `shorts_capa_personalizada` por canal; estado `nao_elegivel`; geração de Short opcional |
| Legenda automática ruim | `--forcar-whisper` por vídeo |
| Transcrição longa demais | Truncar/resumir em blocos |
| SDXL gerando letras ou rostos deformados | `negative_prompt` forte; pessoas em silhueta/distância; título só pelo Pillow |
| Fonte fina ilegível em tamanho pequeno | Peso Light, véu + sombra, teste em miniatura obrigatório |
| VRAM de 8 GB | fp16, VAE tiling, attention slicing, um modelo por GPU |
| Token vencendo em 7 dias | Aviso + `yt-thumbnail auth`; documentar publicação do app |
| Cota (~50 unidades por capa) | Enviar só aprovados; lotes diários |
| Job apontando para o canal errado | Conferência `channel_id` vídeo × token antes do envio |
| Vazamento de segredo no GitHub | `.gitignore` desde a Fase 0, `gitleaks` na Fase 9, `SECURITY.md` |
| Dependência do Claude Code para quem baixar o projeto | Backend de análise plugável e documentado |

## 12. Pontos em aberto

- [x] Vídeos da playlist: sempre de canais próprios (vários canais)
- [x] Identidade visual: preset **Espiritualidade** (seção 5)
- [x] 3 variações por vídeo
- [x] SDXL 1.0 base
- [x] Revisão por HTML estático
- [x] Licença: GNU GPL v3.0
- [x] Nome: **yt-thumbnail**
- [x] Símbolos religiosos: sempre neutros
- [x] Programa de Parcerias: nenhum canal está → sem envio de capa de Short por enquanto

- [ ] Execução: o projeto roda em **outro PC** da rede (2× RTX 3060 Ti 8 GB, acesso `ssh pc-gpu`); o desenvolvimento é feito em outro PC e sincronizado pelo GitHub
- [ ] RAM do PC das GPUs é **8 GB**: carregar SDXL (~7 GB) e Whisper (~3 GB) juntos pode estourar a memória → na Fase 8, permitir rodar as etapas em sequência (paralelismo configurável) ou aumentar a RAM para 16–32 GB
- [ ] `claude -p` por SSH precisa de `CLAUDE_CODE_OAUTH_TOKEN` (ver `docs/solucao-de-problemas.md`)
- [ ] GPU 1 (barramento PCIe 4) do PC das GPUs falhou em 2026-11-05 (erros WHEA no PCIe, depois sumiu do sistema). Até o hardware ser verificado, o PC roda com **uma GPU só** (todas as chaves de `gpu` em `0` e `imagem.cpu_offload: true`: ~81 s por imagem no SDXL, contra ~52 s com as duas; RAM no limite). Quando voltar: `gpu.imagem: 0` (UNet) e `gpu.texto_sdxl: 1`
