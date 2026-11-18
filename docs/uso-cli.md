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

### `yt-thumbnail listar [--job nome] [--ids ...] [--forcar] [--so-novos]`

`--so-novos` mostra na tabela só os vídeos que entraram agora (o `tudo` usa assim).

Lê a playlist de cada job com o yt-dlp (sem API key e sem baixar mídia), consulta os metadados de cada vídeo e detecta o tipo:

- **Short**: duração ≤ 180 s **e** vertical (altura > largura);
- **longo**: todo o resto.

Se a playlist informar mais vídeos do que o yt-dlp conseguiu ler (o yt-dlp às vezes para nos 100 primeiros, sem aviso), os IDs que faltam vêm da **YouTube Data API**, com o login do canal do job (`auth`). Custa ~1 unidade da cota por 50 vídeos e só acontece nesse caso. O resumo informa quantos vieram pela API; sem login, aparece um aviso com quantos ficaram de fora.

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

Em jobs com `fonte_analise: titulo` (ver [configuracao.md](configuracao.md#jobs)), não baixa nada: registra uma transcrição vazia de origem `desativada` na hora, e a análise usa só o título e a descrição.

| Opção | Descrição |
|---|---|
| `--tipo` | só `longo` ou só `short` |
| `--forcar-whisper` | ignora a legenda e transcreve com o Whisper (útil quando a legenda automática é ruim) |
| `--limite N` | processa no máximo N vídeos pendentes, dos publicados mais recentemente para os mais antigos (bom para testar) |

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

- O modelo é carregado uma vez por execução (~10 s). Numa RTX 3060 Ti: ~52 s por imagem com duas GPUs; ~60–80 s com uma GPU só e `cpu_offload`. A primeira execução baixa o SDXL (~7 GB) do Hugging Face.
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

## Escolher os vídeos

### `yt-thumbnail selecionar [--job] [--tipo] [--nao-abrir] [--porta]`

Abre uma página (pelo mesmo servidor local do `revisar --servir`, só em 127.0.0.1) com os vídeos que **ainda não ganharam capa nova**, dos mais recentes para os mais antigos. Cada um aparece com a capa atual do YouTube, o título e a data. Para Shorts, é a capa vertical.

1. Marque os vídeos que você **não** quer trocar de capa. Clicar no cartão marca e desmarca; o campo de filtro procura pelo título e **Marcar todos (visíveis)** marca o que o filtro mostra.
2. Clique em **Não trocar a capa dos marcados**. Eles saem da fila, ficam como `ignorado` e mantêm a capa atual.
3. Feche com **Ctrl+C** e rode o `tudo` normalmente.

Um vídeo ignorado nunca é transcrito, analisado, gerado, revisado nem enviado, e o `listar` não o traz de volta. Para desfazer, abra **Ignorados** no fim da página, marque o vídeo e clique em **Voltar para a fila os marcados**. Ele volta no ponto em que estava, e as imagens já geradas são aproveitadas.

Só dá para ignorar vídeos ainda não decididos na revisão (de `listado` a `capas_compostas`). Um vídeo que já tinha capas prontas também sai da página de revisão.

```powershell
yt-thumbnail listar --job meditacoes             # busca os vídeos novos da playlist
yt-thumbnail selecionar --job meditacoes --tipo short
```

Pela linha de comando, sem a página:

```powershell
yt-thumbnail selecionar 95lfS2LKuME 68bbQ6lopBE --ignorar
yt-thumbnail selecionar 95lfS2LKuME --incluir
```

## Revisão e aprovação

Nada é enviado ao YouTube sem passar por aqui.

### `yt-thumbnail revisar [--job] [--tipo] [--nao-abrir] [--offline] [--historico] [--servir] [--porta]`

1. Baixa a **capa atual** de cada vídeo com capas compostas para `capa_original.jpg`. É o **backup** usado por `restaurar` (Fase 7): baixado uma única vez e nunca sobrescrito, mesmo com o comando repetido.
2. Gera `saida/<job>/revisao.html` com os vídeos **aguardando decisão** e abre no navegador (`--nao-abrir` só gera; `--offline` não acessa o YouTube; `--historico` inclui também os já aprovados, rejeitados e enviados).

A página fica sempre limpa: `aprovar` e `rejeitar` a regravam na hora, tirando os vídeos decididos (basta recarregar o navegador). Quando não sobra nenhum, ela mostra "Nenhum vídeo aguardando revisão".

A página mostra, por vídeo: selo LONGO/SHORT, título do vídeo (link para o YouTube), situação (aguardando, aprovada a variação N, rejeitado), título da capa e resumo da análise, a capa atual, as variações em tamanho real e em miniatura (320×180 ou 180×320, como aparecem na busca e nas sugestões), as métricas da composição (fonte, contraste, tamanho) e, ao lado de cada variação, o botão **Aprovar esta** (com `--servir`) ou o comando de aprovação com um botão **copiar** (página aberta como arquivo). Com `--historico`, os pendentes aparecem primeiro e a variação aprovada fica com borda verde.

![Página de revisão](img/revisao.jpg)

#### Aprovar com um clique: `--servir`

```powershell
yt-thumbnail revisar --servir
```

Sobe um servidor local em `http://127.0.0.1:8765/` e abre a página por ele. Assim, cada variação ganha um botão **Aprovar esta**, cada vídeo um botão **Rejeitar**, e o topo um **Aprovar a variação 1 de todos** (pede confirmação). O clique grava a decisão na hora, como os comandos `aprovar` e `rejeitar`, e o vídeo sai da página. Deixe o terminal aberto enquanto revisa; **Ctrl+C** encerra. Cada decisão aparece também no terminal.

- O servidor escuta só neste PC (127.0.0.1), confere o endereço pedido e exige um token que vai dentro da página servida, então outros sites e outros PCs da rede não conseguem aprovar nada.
- Ele só aprova e rejeita: **nada é enviado ao YouTube**. Depois de revisar, rode `enviar --aprovados --dry-run`.
- Se a porta 8765 estiver ocupada (outra revisão aberta, por exemplo), use `--porta 8766`.
- Aberta direto do arquivo (sem `--servir`), a página continua mostrando os comandos para copiar.

O `--servir` só aceita o navegador do próprio PC onde roda. Se você controla o PC das GPUs por SSH, rode o `revisar --servir` sentado nele (ou por Área de Trabalho Remota); pelo SSH, use `revisar --nao-abrir` e abra o arquivo `revisao.html` lá ou pela rede, copiando os comandos (a página usa caminhos relativos: copiar a pasta `saida/<job>` inteira também funciona).

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

## YouTube: login, envio e restauração

Antes, crie o OAuth client no Google Cloud: [google-oauth.md](google-oauth.md).

### `yt-thumbnail auth --canal APELIDO [--nao-abrir]`

Login OAuth de um canal (abre o navegador **no computador onde roda**). Guarda o token em `secrets/tokens/<channel_id>.json` e preenche o `channel_id` do canal no `config.yaml` se estiver vazio; se estiver preenchido com outro canal, recusa.

### `yt-thumbnail canais`

Tabela com os canais do `config.yaml`: `channel_id`, situação do login (OK, falta `auth`, venceu), nome do canal no YouTube, se aceita capa de Short e quais jobs usam o canal.

### `yt-thumbnail enviar --aprovados [--dry-run] [--job] [--ids] [--tipo] [--limite N]`

Envia (`thumbnails.set`) as capas **aprovadas**. Rode primeiro com `--dry-run`: mostra o que seria enviado, sem acessar a API.

Para cada vídeo aprovado, nesta ordem:

1. o canal do vídeo precisa ser o canal do job (senão: **pulado**);
2. o backup `capa_original.jpg` precisa existir (senão: **pulado** — rode `revisar`);
3. Short em canal com `shorts_capa_personalizada: false` (ou que a API recusa com 403) → **não elegível** (ver [shorts.md](shorts.md));
4. envio, com pausa aleatória de `envio.pausa_segundos` entre vídeos e novas tentativas em 429/5xx.

Depois do envio: status `enviado` e `envio.json` na pasta do vídeo (data, variação, resposta da API e histórico). Cota esgotada para o lote (continue no dia seguinte; ver [google-oauth.md](google-oauth.md#4-cota-da-api)).

```powershell
yt-thumbnail enviar --aprovados --dry-run
yt-thumbnail enviar --aprovados --limite 20
```

### `yt-thumbnail restaurar ID [ID...] [--job]`

Envia de volta a capa original (`capa_original.jpg`) e marca o vídeo como `rejeitado` (não será reenviado). Se o vídeo não tinha capa personalizada, o quadro automático que o YouTube usava passa a ser a capa enviada (mesma imagem).

## Tudo de uma vez

### `yt-thumbnail tudo [--job] [--tipo] [--limite N] [--ate ETAPA] [--abrir]`

Roda `listar → transcrever → analisar → gerar → compor → revisar` e **para na revisão** — o envio é sempre um comando à parte (`enviar --aprovados`).

- Cada etapa só processa o que falta: rodar de novo continua de onde parou (inclusive depois de queda de energia ou erro). Vídeos já enviados, aprovados ou rejeitados não são refeitos; os que aguardam revisão só voltam à página.
- Erro num vídeo não para o fluxo: fica no estado e aparece no resumo. Uma etapa que falha inteira (ex.: playlist inacessível) também não impede as seguintes de processar o que já existe. Só erro de configuração interrompe.
- `--limite N`: no máximo N vídeos **novos** por etapa e por job (útil para lotes: `--limite 20` toda noite). Os já processados não contam.
- `--job` e `--tipo`: só uma playlist e/ou só um formato (`longo` ou `short`).
- `--ate gerar`: para depois da etapa indicada.
- `--abrir`: abre a página de revisão (como arquivo) no fim. O padrão é não abrir, pensando em execução por SSH ou agendada; o resumo final sugere `revisar --servir` quando há vídeos aguardando.
- No fim, um resumo: tempo de cada etapa e, por job, vídeos, quantos chegaram à revisão, pendentes, aprovados, enviados, não elegíveis e erros (com a etapa e a mensagem).
- Tudo o que aparece no terminal vai também para `saida/logs/tudo-AAAAMMDD-HHMMSS.log`.

As etapas rodam **uma depois da outra**: com 8 GB de RAM, Whisper e SDXL carregados juntos estouram a memória. Entre as etapas os modelos são liberados.

```powershell
yt-thumbnail tudo                      # todos os jobs, tudo o que falta
yt-thumbnail tudo --job palestras --limite 10
yt-thumbnail tudo --tipo short --limite 10            # só os Shorts, de todos os jobs
yt-thumbnail tudo --job meditacoes --tipo longo       # só os longos de um job
```

Depois, o fluxo segue com a revisão e o envio:

```powershell
yt-thumbnail revisar --servir                 # aprove/rejeite pelos botões; Ctrl+C encerra
yt-thumbnail enviar --aprovados --dry-run     # confira o que vai
yt-thumbnail enviar --aprovados               # envia ao YouTube
```

Para rodar todo dia sozinho, agende no **Agendador de Tarefas** do Windows: programa `C:\Users\<você>\yt-thumbnail\.venv\Scripts\yt-thumbnail.exe`, argumentos `tudo --limite 20`, iniciar em `C:\Users\<você>\yt-thumbnail`.
