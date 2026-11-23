# Tutorial: trocando as capas, do começo ao fim

Este é o roteiro completo para trocar as capas dos vídeos de uma playlist, com todos os comandos na ordem em que você vai usá-los. A referência de cada opção está em [uso-cli.md](uso-cli.md); a instalação, em [instalacao-windows.md](instalacao-windows.md).

**O caminho, em resumo:**

```
listar → selecionar → tudo → revisar --servir → enviar --dry-run → enviar
 (busca)  (escolhe)   (gera)    (aprova)          (confere)        (publica)
```

Nada vai para o YouTube antes do último passo, e cada passo pode ser repetido sem estragar nada: o programa só faz o que falta.

---

## 0. Antes de começar (uma vez só)

Você precisa ter feito, uma vez:

1. a instalação ([instalacao-windows.md](instalacao-windows.md)), terminando com `yt-thumbnail ambiente` sem erros;
2. o `config.yaml` com os canais e as playlists ([configuracao.md](configuracao.md));
3. o OAuth client no Google Cloud e o login do canal ([google-oauth.md](google-oauth.md)).

### Abrindo o terminal certo

Todos os comandos rodam **no PC das GPUs**, no PowerShell, dentro da pasta do projeto:

```powershell
cd $env:USERPROFILE\yt-thumbnail
.\.venv\Scripts\Activate.ps1
```

Depois do `Activate.ps1`, o começo da linha mostra `(.venv)` e você digita só `yt-thumbnail ...`. Sem ativar, use o caminho inteiro, que funciona do mesmo jeito:

```powershell
.\.venv\Scripts\yt-thumbnail listar
```

### Conferindo se está tudo pronto

```powershell
yt-thumbnail validar        # o config.yaml está certo? lista os jobs (playlists)
yt-thumbnail canais         # o login de cada canal está OK?
```

Se o `canais` mostrar o login vencido ou faltando, entre de novo (abre o navegador **neste** PC):

```powershell
yt-thumbnail auth --canal espiritual-principal
```

> Com o app do Google Cloud em modo **Teste**, o login vence a cada 7 dias. Quando vencer, os comandos que falam com o YouTube (`enviar`, `restaurar` e a parte do `listar` que completa playlists grandes) avisam; basta repetir o `auth`.

---

## 1. Buscar os vídeos novos: `listar`

```powershell
yt-thumbnail listar                       # todas as playlists
yt-thumbnail listar --job meditacoes      # só uma
```

Lê cada playlist configurada, descobre se cada vídeo é **longo** ou **Short** e guarda os dados (título, data, duração). Não baixa vídeo nenhum. Na primeira vez demora (alguns segundos por vídeo); nas seguintes, só os vídeos novos são consultados.

No fim aparece um resumo como:

```
241 vídeo(s): 0 longo(s), 241 Short(s); 3 novo(s), 238 já listado(s), 0 erro(s).
```

- Vídeos de um tipo que o job não usa (por exemplo, Shorts num job com `tipos: [longo]`) aparecem como "fora do job" e são deixados de lado.
- Playlists com mais de 100 vídeos são completadas pela YouTube Data API, com o login do canal; o resumo diz quantos vieram por ela.
- Vídeo que não está em nenhuma playlist configurada **não é visto**. Para ele entrar, coloque-o na playlist pelo YouTube Studio e rode `listar` de novo.

Você não precisa rodar o `listar` sozinho: o `tudo` (passo 3) começa por ele. Rode à parte quando quiser **escolher** os vídeos antes de gerar (passo 2).

---

## 2. Escolher quais vídeos ganham capa nova: `selecionar`

Por padrão, **todo** vídeo da playlist entra na fila. Se alguns devem manter a capa que têm hoje, tire-os da fila antes de gerar:

```powershell
yt-thumbnail selecionar --job meditacoes --tipo short
```

Abre no navegador uma página com os vídeos que ainda não ganharam capa nova, do mais recente para o mais antigo, cada um com a **capa atual**, o título e a data.

1. Clique nos cartões dos vídeos que você **NÃO** quer trocar (ficam com borda vermelha). Clicar de novo desmarca.
   - O campo **Filtrar pelo título** ajuda a achar ("Divaldo", "Prece"...).
   - **Marcar todos (visíveis)** marca o que o filtro está mostrando.
   - Clicar no título abre o vídeo no YouTube.
2. Clique em **Não trocar a capa dos marcados** e confirme. Eles vão para a seção **Ignorados**, no fim da página.
3. Quando terminar, volte ao terminal e aperte **Ctrl+C**.

Um vídeo ignorado nunca é processado nem enviado, e o `listar` não o traz de volta. Mudou de ideia? Abra **Ignorados**, marque o vídeo e clique em **Voltar para a fila os marcados**.

Também dá para fazer pelo terminal, com os IDs dos vídeos (o trecho depois de `v=` ou de `/shorts/` no endereço):

```powershell
yt-thumbnail selecionar 95lfS2LKuME 68bbQ6lopBE --ignorar
yt-thumbnail selecionar 95lfS2LKuME --incluir
```

> A página só funciona com o terminal aberto (ela conversa com o programa). Use-a sentado no PC das GPUs ou por Área de Trabalho Remota/TeamViewer: por SSH, o navegador de outro computador não consegue acessá-la.

---

## 3. Gerar as capas: `tudo`

```powershell
yt-thumbnail tudo --job meditacoes --tipo short --limite 10
```

Faz, em sequência, para os vídeos da fila:

| Etapa | O que faz | Tempo aproximado (RTX 3060 Ti) |
|---|---|---|
| `listar` | busca vídeos novos | segundos |
| `transcrever` | legenda do YouTube ou Whisper na GPU | 0–7 min por vídeo (Short: segundos) |
| `analisar` | Claude Code lê o conteúdo e cria o título da capa e a ideia da imagem | ~30 s por vídeo |
| `gerar` | SDXL cria 3 imagens de fundo, sem texto | ~1 min por imagem (~3 min por vídeo) |
| `compor` | escreve o título sobre as imagens | menos de 1 s |
| `revisar` | baixa a capa atual (backup) e monta a página de revisão | segundos |

E **para aí**: nada é enviado.

**As opções que você mais vai usar:**

| Opção | Para quê |
|---|---|
| `--job meditacoes` | só uma playlist (sem ela: todas) |
| `--tipo short` / `--tipo longo` | só Shorts ou só vídeos longos |
| `--limite 10` | no máximo 10 vídeos **novos** por etapa; os **mais recentes primeiro** |
| `--ate gerar` | para depois de uma etapa (`listar`, `transcrever`, `analisar`, `gerar`, `compor`) |
| `--abrir` | abre a página de revisão (como arquivo) no fim |

Exemplos:

```powershell
yt-thumbnail tudo --limite 10                            # 10 de cada playlist
yt-thumbnail tudo --job palestras --limite 10            # só palestras
yt-thumbnail tudo --tipo short --limite 10               # só Shorts, de todas as playlists
yt-thumbnail tudo --ate listar                           # só busca e mostra o resumo
```

**Pode interromper?** Pode. Ctrl+C, queda de energia, erro: rode o mesmo comando de novo e ele continua de onde parou. O que já foi feito não é refeito, e vídeos já enviados não voltam para a fila.

No fim aparece um resumo por playlist (vídeos, na revisão, pendentes, aprovados, enviados, erros) e tudo fica gravado em `saida\logs\tudo-AAAAMMDD-HHMMSS.log`.

### Etapa por etapa (opcional)

O `tudo` é só um atalho. Cada etapa também roda sozinha, com as mesmas opções `--job`, `--tipo`, `--limite` e `--ids`:

```powershell
yt-thumbnail transcrever --job palestras --limite 3
yt-thumbnail analisar --job palestras --limite 3
yt-thumbnail gerar --job palestras --limite 3
yt-thumbnail compor --job palestras
```

---

## 4. Revisar e aprovar: `revisar --servir`

```powershell
yt-thumbnail revisar --servir
```

Abre a página de revisão no navegador. Para cada vídeo aparecem a **capa atual** e **3 variações** novas, em tamanho real e em miniatura (do jeito que aparecem na busca do YouTube).

- **Aprovar esta**: escolhe aquela variação. O vídeo sai da página.
- **Rejeitar (nenhuma serve)**: o vídeo não recebe capa nova (por enquanto; veja abaixo como tentar de novo).
- **Aprovar a variação 1 de todos** (no topo): aprova a primeira de todos os pendentes, com confirmação.

Cada decisão aparece também no terminal. Quando terminar, **Ctrl+C**. Aprovar **não envia nada**.

Filtre como no `tudo`: `yt-thumbnail revisar --servir --job meditacoes --tipo short`.

### Pelo terminal, sem a página

```powershell
yt-thumbnail aprovar 95lfS2LKuME --variacao 2
yt-thumbnail aprovar --todos --variacao 1 --job palestras
yt-thumbnail rejeitar 95lfS2LKuME
```

Dá para mudar de ideia até o envio: aprovar outra variação, aprovar um rejeitado ou rejeitar um aprovado.

### Nenhuma variação ficou boa

Gere imagens novas para o vídeo e componha de novo. Ele volta para a página de revisão:

```powershell
yt-thumbnail gerar --ids 95lfS2LKuME --forcar
yt-thumbnail compor --ids 95lfS2LKuME
yt-thumbnail revisar --servir
```

Se o problema é o **título** da capa (e não a imagem), refaça também a análise:

```powershell
yt-thumbnail analisar --ids 95lfS2LKuME --forcar
yt-thumbnail gerar --ids 95lfS2LKuME --forcar
yt-thumbnail compor --ids 95lfS2LKuME --forcar
```

---

## 5. Enviar ao YouTube: `enviar`

**Sempre simule primeiro:**

```powershell
yt-thumbnail enviar --aprovados --dry-run
```

Mostra o que seria enviado, sem tocar no YouTube. Estando certo, envie, de preferência em lotes:

```powershell
yt-thumbnail enviar --aprovados --limite 15
```

- Entre um envio e outro há uma pausa de **30 a 60 segundos** (`envio.pausa_segundos`), para o YouTube não bloquear. 15 capas levam uns 11 minutos.
- Antes de cada envio o programa confere se o vídeo é do canal certo e se o backup da capa atual existe. Se algo não bate, o vídeo é **pulado**, com o motivo.
- Filtros: `--job`, `--tipo`, `--ids`.

**Se aparecer `uploadRateLimitExceeded` (HTTP 429):** o YouTube limitou os envios por um tempo. Nada se perde: os vídeos continuam aprovados. Espere algumas horas e rode o mesmo `enviar --aprovados --limite 15` de novo; só vão os que faltam.

**Se aparecer `quotaExceeded`:** acabou a cota diária da API (~200 capas por dia). O lote para e continua no dia seguinte, com o mesmo comando.

Depois de enviada, a capa nova pode levar alguns minutos para aparecer no YouTube.

---

## 6. Voltar a capa antiga: `restaurar`

Não gostou de uma capa já publicada?

```powershell
yt-thumbnail restaurar 95lfS2LKuME
```

Envia de volta a capa que o vídeo tinha antes (o backup `capa_original.jpg`, salvo na revisão) e marca o vídeo como rejeitado, para ele não ser reenviado. Em Shorts, a capa volta na vertical. Para tentar outra capa depois, gere de novo (passo 4, "Nenhuma variação ficou boa"), aprove e envie.

---

## 7. Receitas do dia a dia

### Rotina recomendada

```powershell
yt-thumbnail listar
yt-thumbnail selecionar                                  # opcional: tire o que não quer trocar
yt-thumbnail tudo --limite 10
yt-thumbnail revisar --servir                            # aprove; Ctrl+C
yt-thumbnail enviar --aprovados --dry-run
yt-thumbnail enviar --aprovados --limite 15
```

### Só as palestras / só os Shorts

```powershell
yt-thumbnail tudo --job palestras --limite 10
yt-thumbnail tudo --job meditacoes --tipo short --limite 10
yt-thumbnail revisar --servir --job meditacoes --tipo short
yt-thumbnail enviar --aprovados --job meditacoes --tipo short --limite 15
```

### Um vídeo específico

Ele precisa estar numa playlist configurada. Use o ID com `--ids` nas etapas:

```powershell
yt-thumbnail listar --job meditacoes --ids 95lfS2LKuME
yt-thumbnail transcrever --ids 95lfS2LKuME
yt-thumbnail analisar --ids 95lfS2LKuME
yt-thumbnail gerar --ids 95lfS2LKuME
yt-thumbnail compor --ids 95lfS2LKuME
yt-thumbnail revisar --servir
yt-thumbnail enviar --aprovados --ids 95lfS2LKuME
```

### Vídeos novos do canal

Publicou vídeos novos? Basta que estejam numa playlist configurada: o próximo `tudo` (ou `listar`) os encontra, e com `--limite` eles são os **primeiros** a ser processados.

### Incluir outra playlist

Acrescente um bloco em `jobs:` no `config.yaml` (exemplo em [configuracao.md](configuracao.md#exemplo-com-várias-playlists)), confira e teste com poucos vídeos:

```powershell
yt-thumbnail validar
yt-thumbnail tudo --job nome-novo --limite 3
```

### Deixar rodando sozinho toda noite

No **Agendador de Tarefas** do Windows, crie uma tarefa com:

- programa: `C:\Users\<você>\yt-thumbnail\.venv\Scripts\yt-thumbnail.exe`
- argumentos: `tudo --limite 20`
- iniciar em: `C:\Users\<você>\yt-thumbnail`

De manhã, só falta revisar e enviar. O envio nunca é automático.

---

## 8. Quadro-resumo dos comandos

| Comando | Para quê |
|---|---|
| `yt-thumbnail ambiente` | confere a instalação (GPU, Python, FFmpeg, Claude Code) |
| `yt-thumbnail validar` | confere o `config.yaml` e lista as playlists |
| `yt-thumbnail canais` | situação do login de cada canal |
| `yt-thumbnail auth --canal APELIDO` | faz (ou refaz) o login de um canal |
| `yt-thumbnail listar` | busca os vídeos das playlists |
| `yt-thumbnail selecionar` | escolhe quais vídeos **não** devem trocar de capa |
| `yt-thumbnail tudo` | listar → transcrever → analisar → gerar → compor → revisar |
| `yt-thumbnail transcrever` / `analisar` / `gerar` / `compor` | as etapas do `tudo`, uma por vez |
| `yt-thumbnail revisar --servir` | página para aprovar e rejeitar com um clique |
| `yt-thumbnail aprovar ID --variacao N` | aprova pelo terminal |
| `yt-thumbnail rejeitar ID` | rejeita pelo terminal |
| `yt-thumbnail enviar --aprovados --dry-run` | mostra o que seria enviado |
| `yt-thumbnail enviar --aprovados` | envia as capas aprovadas ao YouTube |
| `yt-thumbnail restaurar ID` | volta a capa original de um vídeo |

Todo comando tem ajuda: `yt-thumbnail <comando> --help`.

## 9. O caminho de cada vídeo

| Situação | O que significa | Próximo passo |
|---|---|---|
| `listado` | encontrado na playlist | `tudo` |
| `transcrito` / `analisado` / `imagens_geradas` | no meio da geração | `tudo` continua |
| `capas_compostas` | 3 capas prontas, aguardando você | `revisar --servir` |
| `aprovado` | você escolheu uma variação | `enviar --aprovados` |
| `enviado` | capa nova publicada | nada (ou `restaurar`) |
| `rejeitado` | nenhuma variação serviu, ou foi restaurado | `gerar --ids ID --forcar` para tentar de novo |
| `ignorado` | você escolheu manter a capa atual | nada (ou `selecionar ID --incluir`) |
| `nao_elegivel` | Short num canal que não aceita capa personalizada | ver [shorts.md](shorts.md) |

Algo deu errado? Veja [solucao-de-problemas.md](solucao-de-problemas.md).
