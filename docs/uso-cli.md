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

### `yt-thumbnail analisar [--job] [--ids] [--tipo] [--forcar] [--limite N]`

Para cada vídeo transcrito, envia título, descrição, transcrição e o tom do preset ao backend de análise (padrão: Claude Code, `claude -p`) e recebe o **título da capa** e o **prompt de imagem**. Grava `analise.json`, registra `analisado` e mostra uma tabela com os títulos gerados.

- A resposta é validada (esquema JSON e tamanho do título definido no preset); se vier inválida, o modelo recebe o motivo e tenta de novo (até `analise.tentativas` vezes a mais).
- Se o backend não puder ser usado (Claude Code ausente ou sem login), o comando para logo no primeiro vídeo, com a instrução do que fazer.

```powershell
yt-thumbnail analisar --job palestras --limite 5
yt-thumbnail analisar --ids ID_DO_VIDEO --forcar
```

### `yt-thumbnail gerar [--job] [--ids] [--tipo] [--variacoes N] [--forcar] [--limite N]`

Gera as imagens de fundo, **sem texto**, com o SDXL na GPU `gpu.imagem`, para os vídeos já analisados. Cada vídeo recebe `--variacoes` imagens (padrão `imagem.variacoes`, 3) com seeds diferentes, geradas na resolução nativa do tipo (1344×768 longo, 768×1344 Short) e ajustadas para a saída (1280×720 / 1080×1920). Grava `base_1..N.png` e `imagens.json` (seeds e parâmetros) e registra `imagens_geradas`.

- O modelo é carregado uma vez por execução (~10 s; ~52 s por imagem numa RTX 3060 Ti); a primeira execução baixa o SDXL (~7 GB) do Hugging Face.
- `--forcar` gera de novo com seeds novas.

```powershell
yt-thumbnail gerar --job palestras --limite 2
yt-thumbnail gerar --ids ID_DO_VIDEO --forcar --variacoes 4
```

### `yt-thumbnail compor [--job] [--ids] [--tipo] [--forcar] [--limite N]`

Escreve o `titulo_capa` da análise sobre cada imagem de fundo, com a tipografia do preset, para os vídeos com imagens geradas. Grava, por variação, `capa_N.jpg` (JPEG, sempre < 2 MB) e `mini_N.jpg` (miniatura de verificação, 320×180 ou 180×320), além de `capas.json`, e registra `capas_compostas`. Leva menos de 1 s por capa e não usa GPU.

- Pula vídeos já compostos; recompõe sozinho se as imagens forem geradas de novo depois.
- `--forcar` recompõe (útil depois de mudar a tipografia do preset).
- Avisos de legibilidade aparecem no fim (ver [presets.md](presets.md#camada-de-tipografia)).

```powershell
yt-thumbnail compor
yt-thumbnail compor --job palestras --forcar
```

## Revisão e aprovação

Nada é enviado ao YouTube sem passar por aqui.

### `yt-thumbnail revisar [--job] [--tipo] [--nao-abrir] [--offline]`

1. Baixa a **capa atual** de cada vídeo com capas compostas para `capa_original.jpg`. É o **backup** usado por `restaurar` (Fase 7): baixado uma única vez e nunca sobrescrito, mesmo com o comando repetido.
2. Gera `saida/<job>/revisao.html` e abre no navegador (`--nao-abrir` só gera; `--offline` não acessa o YouTube).

A página mostra, por vídeo: selo LONGO/SHORT, título do vídeo (link para o YouTube), situação (aguardando, aprovada a variação N, rejeitado), título da capa e resumo da análise, a capa atual, as variações em tamanho real e em miniatura (320×180 ou 180×320, como aparecem na busca e nas sugestões), as métricas da composição (fonte, contraste, tamanho) e, ao lado de cada variação, o comando de aprovação com um botão **copiar**. Vídeos pendentes aparecem primeiro; a variação aprovada fica com borda verde.

![Página de revisão](img/revisao.jpg)

Executando no PC das GPUs por SSH, use `--nao-abrir` e abra o arquivo lá, ou pela rede (a página usa caminhos relativos: copiar a pasta `saida/<job>` inteira também funciona).

### `yt-thumbnail aprovar ID [ID...] --variacao N [--job] [--forcar]`

Aprova a variação `N` (1, 2, 3...) dos vídeos e registra `aprovado` (com a variação e o arquivo da capa no estado). Sem `--job`, procura o vídeo em todos os jobs (se estiver em mais de um, pede `--job`).

```powershell
yt-thumbnail aprovar sFPmqrUSXlw --variacao 2
yt-thumbnail aprovar --todos --variacao 1          # todos os pendentes de revisão
yt-thumbnail aprovar --todos --variacao 1 --job palestras --tipo longo
```

### `yt-thumbnail rejeitar ID [ID...] [--job] [--forcar]`

Rejeita as capas do vídeo: ele não será enviado. Para tentar de novo, gere outras imagens (`gerar --ids ID --forcar`) e componha (`compor --ids ID`): o vídeo volta a ficar pendente.

Mudar de ideia é livre até o envio (aprovar outra variação, rejeitar um aprovado ou aprovar um rejeitado). Depois de `enviado`, só com `--forcar`. Recompor com `compor --forcar` também desfaz a decisão.

## Comandos planejados

`enviar`, `restaurar`, `auth`, `canais`, `tudo` — entram nas próximas fases (ver `PLANO.md`).
