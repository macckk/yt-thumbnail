# Solução de problemas

## Ambiente

### `nvidia-smi` não encontrado / nenhuma GPU

Instale ou atualize o driver NVIDIA e reinicie (ver [instalacao-windows.md](instalacao-windows.md#1-driver-nvidia)).

### `torch.cuda.is_available()` retorna `False`

O PyTorch instalado é só-CPU. Reinstale pelo índice com CUDA:

```powershell
pip uninstall -y torch
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

### Não há pacote do PyTorch/CTranslate2 para a minha versão do Python

Crie o venv com uma versão anterior do Python (3.12 é a mais segura): `py -3.12 -m venv .venv`.

### CUDA e cuDNN

Erros como `Could not load library cudnn_ops64_9.dll` ou `cublas64_12.dll not found` no faster-whisper indicam que faltam as DLLs do CUDA 12:

```powershell
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
```

Ou use as DLLs do pacote do Purfview e coloque a pasta no `PATH`.

### FFmpeg não encontrado

`winget install Gyan.FFmpeg` e **reabra o terminal** para atualizar o `PATH`.

### Comando `claude` não encontrado

Instale o Claude Code e confira com `claude --version` num terminal novo.

### Fontes ausentes

`python scripts/baixar_fontes.py` (com `pip install fonttools` para fixar o peso Light).

### `claude -p` responde "Not logged in" por SSH

No terminal local o `claude -p "diga ok"` funciona, mas pelo SSH responde `Not logged in · Please run /login`. Em sessões SSH autenticadas por chave, o Windows não libera as credenciais protegidas do usuário, então o login normal do Claude Code não é lido.

Solução: gerar um token de longa duração e guardá-lo numa variável de ambiente do usuário (no PC das GPUs, terminal local):

```powershell
claude setup-token
[Environment]::SetEnvironmentVariable('CLAUDE_CODE_OAUTH_TOKEN', 'TOKEN_GERADO', 'User')
```

Depois, como Administrador, `Restart-Service sshd`. O token é um segredo: não o coloque em `config.yaml`, `.env` versionado nem em commits.

## Listagem (yt-dlp)

### `Não foi possível ler a playlist`

- Confira se a playlist é **pública** ou **não listada** (privada não funciona sem login).
- Atualize o yt-dlp: `pip install -U yt-dlp`. O YouTube muda com frequência e versões antigas param de funcionar.

### `Sign in to confirm you're not a bot`

O YouTube está bloqueando o acesso anônimo. Defina `ytdlp.cookies_navegador: firefox` (ou o navegador onde você está logado no YouTube) no `config.yaml`. No Chrome/Edge, feche o navegador antes, porque o arquivo de cookies fica bloqueado enquanto ele está aberto.

### Um vídeo foi classificado com o tipo errado

A regra é: Short = duração ≤ 180 s **e** vertical. Veja `largura`, `altura`, `duracao` e `tipo_origem` em `saida/<job>/<id>/meta.json`. `tipo_origem: url_shorts` indica que o yt-dlp não informou as dimensões e o tipo foi decidido consultando `youtube.com/shorts/<id>`. Para refazer: `yt-thumbnail listar --ids <id> --forcar`.

## Transcrição

### `Unable to download video subtitles ... HTTP Error 429: Too Many Requests`

O YouTube limitou o download de legendas para o seu IP (comum depois de muitas consultas seguidas). Com `whisper_se_legenda_falhar: true` (padrão), a transcrição segue pelo Whisper e o motivo fica em `legenda_erro` no `transcricao.json`; o resumo do comando mostra um aviso.

- O bloqueio costuma passar em algumas horas. Para refazer pela legenda depois: `yt-thumbnail transcrever --ids ID --forcar`.
- Confirme que `curl_cffi` e `deno` estão instalados (vêm com `pip install -e .`): `python -m yt_dlp --list-impersonate-targets` deve listar alvos `curl_cffi`.
- Se persistir, use cookies do navegador (`ytdlp.cookies_navegador`).

### Whisper: `cublas64_12.dll` / `cudnn_ops64_9.dll` não encontrada

Veja [CUDA e cuDNN](#cuda-e-cudnn). O yt-thumbnail já procura as DLLs dos pacotes `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` instalados no venv.

### Whisper lento ou sem memória

- O `large-v3` usa ~3 GB de VRAM em `float16` e leva alguns minutos por hora de áudio numa RTX 3060 Ti. O modelo `turbo` é bem mais rápido, com qualidade um pouco menor: `modelo_whisper: turbo`.
- A primeira execução baixa o modelo (~3 GB) para o cache do Hugging Face (`HF_HOME`).

### Transcrição saiu como `sem_fala`

Não havia legenda e o Whisper não encontrou fala (menos de 20 letras). Normal em Shorts só com música; a análise usará título e descrição. Se houver fala, tente `--forcar-whisper`.

## Análise (Claude Code)

### `O Claude Code não está autenticado nesta sessão`

Rode `claude` uma vez e faça login. Se o yt-thumbnail roda por **SSH**, veja ["claude -p responde Not logged in por SSH"](#claude--p-responde-not-logged-in-por-ssh).

### `resposta inválida após N tentativa(s)`

O modelo não devolveu um JSON válido ou o título ficou fora da faixa de palavras do preset. Rode de novo só esse vídeo (`yt-thumbnail analisar --ids ID --forcar`); se repetir, aumente `analise.tentativas` ou ajuste o template.

### `error: unknown option '--json-schema'` (ou `--tools`)

Sua versão do Claude Code é antiga: atualize (`claude update`) ou defina `analise.saida_estruturada: false`.

### Muito lento ou `não respondeu em 300 s`

Aumente `analise.timeout_segundos` ou use um modelo mais rápido em `analise.modelo` (ex.: `sonnet`).

## Configuração

### `Arquivo de configuração config.yaml não encontrado`

Copie `config.example.yaml` para `config.yaml` na pasta onde roda o comando, ou passe `--config`.

### `Extra inputs are not permitted`

Há uma chave desconhecida no YAML — normalmente erro de digitação. Compare com [configuracao.md](configuracao.md).
