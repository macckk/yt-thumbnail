# Google Cloud e login no YouTube

O envio das capas usa a **YouTube Data API v3** com o **seu próprio** OAuth client. O projeto não distribui credenciais: cada pessoa cria o dela, uma vez, em uns 10 minutos.

- **Um** OAuth client para o projeto: `secrets/client_secret.json`.
- **Um token por canal**: `secrets/tokens/<channel_id>.json`, criado por `yt-thumbnail auth`.

A pasta `secrets/` nunca vai para o git. Não mande esses arquivos para ninguém.

## 1. Criar o projeto no Google Cloud

Pode ser feito em qualquer computador.

1. Acesse **console.cloud.google.com** com uma conta Google (de preferência a que administra os canais).
2. **Projeto:** no seletor de projetos (topo) → **Novo projeto** → nome `yt-thumbnail` → **Criar**. Confira que ele ficou selecionado.
3. **API:** menu ☰ → **APIs e serviços** → **Biblioteca** → busque **YouTube Data API v3** → **Ativar**.
4. **Tela de consentimento:** **APIs e serviços** → **Tela de permissão OAuth** (nas versões novas, **Google Auth Platform**) → **Começar**:
   - nome do app: `yt-thumbnail`; e-mail de suporte: o seu;
   - público: **Externo**;
   - informações de contato: o seu e-mail → aceite a política → **Criar**.
5. **Usuários de teste:** em **Público** (*Audience*) → **Usuários de teste** → **Adicionar usuários** → o e-mail de **cada conta Google que administra um canal**. Sem isso o login é bloqueado ("acesso bloqueado: o app não concluiu a verificação").
6. **Escopos:** em **Acesso a dados** → **Adicionar ou remover escopos** → marque e salve:
   - `https://www.googleapis.com/auth/youtube.upload` (trocar a capa);
   - `https://www.googleapis.com/auth/youtube.readonly` (identificar o canal e conferir os vídeos).
7. **Cliente:** em **Clientes** (ou **Credenciais**) → **Criar cliente** → tipo **App para computador** (*Desktop app*) → nome `yt-thumbnail` → **Criar** → **baixe o JSON na hora** (o Google só mostra o segredo na criação; se perder, crie outro cliente).
8. Renomeie para `client_secret.json` e coloque em `secrets/` na pasta do projeto **do computador que vai enviar as capas** (ex.: `C:\Users\<você>\yt-thumbnail\secrets\client_secret.json`).

## 2. Login de cada canal

O login abre o navegador **no computador onde o comando roda**. Se o projeto roda em outro PC por SSH, faça este passo sentado nele (ou por Área de Trabalho Remota): pelo SSH não há navegador.

```powershell
cd $env:USERPROFILE\yt-thumbnail
.\.venv\Scripts\yt-thumbnail auth --canal espiritual-principal
```

1. O navegador abre; escolha a conta Google do canal.
2. Se a conta tiver vários canais (contas de marca), **escolha o canal** certo.
3. "**O Google não verificou este app**": é esperado (o app é seu) → **Continuar**.
4. Autorize as permissões → "Autorização concluída" → feche a aba.
5. No terminal: nome e ID do canal; o token vai para `secrets/tokens/<channel_id>.json`. Se o `channel_id` do canal estiver vazio no `config.yaml`, ele é preenchido; se já estiver preenchido e for outro canal, o login é recusado (escolha o canal certo e rode de novo).

Repita para cada canal (`--canal <apelido>`). Para conferir todos: `yt-thumbnail canais`.

Sem navegador nesse computador, use `--nao-abrir`: o comando mostra o endereço para abrir em outro lugar, mas o retorno do Google vai para `localhost` **daquele** computador, então isso só funciona com o navegador na mesma máquina.

## 3. Modo Teste × Em produção

| | Teste (padrão) | Em produção |
|---|---|---|
| Quem pode logar | só os usuários de teste (até 100) | qualquer conta (com aviso de app não verificado) |
| Validade do login | **7 dias** — depois `enviar` avisa "login venceu" e é preciso rodar `auth` de novo | não vence (até revogar ou ficar 6 meses sem uso) |
| Verificação do Google | não precisa | para uso pessoal, não é obrigatória: o aviso "app não verificado" continua aparecendo no login |

Para publicar: **Público** → **Publicar app** → confirmar. Para uso pessoal com os seus canais, o modo Teste funciona; publicar só evita refazer o login toda semana.

## 4. Cota da API

Cada projeto tem **10.000 unidades por dia** (renova à meia-noite, horário do Pacífico). Trocar uma capa custa cerca de **50 unidades** → ~200 capas por dia. `enviar` para sozinho quando a cota acaba ("cota diária da API esgotada") e continua de onde parou na próxima execução. Use `--limite N` para enviar em lotes.

## 5. Segurança

- `client_secret.json` e os tokens dão acesso para trocar capas dos seus canais: ficam só em `secrets/` (fora do git).
- Para revogar o acesso: [myaccount.google.com/permissions](https://myaccount.google.com/permissions) → `yt-thumbnail` → **Remover acesso**; depois apague o token em `secrets/tokens/`.
- Antes de enviar, o programa confere se cada vídeo é do canal do token, exige o backup da capa atual (`revisar`) e só envia o que foi aprovado.
