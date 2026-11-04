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

## Configuração

### `Arquivo de configuração config.yaml não encontrado`

Copie `config.example.yaml` para `config.yaml` na pasta onde roda o comando, ou passe `--config`.

### `Extra inputs are not permitted`

Há uma chave desconhecida no YAML — normalmente erro de digitação. Compare com [configuracao.md](configuracao.md).
