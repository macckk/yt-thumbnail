# Instalação no Windows

Passo a passo do zero até `yt-thumbnail ambiente` mostrar tudo OK. Comandos em **PowerShell**.

## 1. Driver NVIDIA

1. Baixe e instale o driver mais recente da sua placa em <https://www.nvidia.com/Download/index.aspx> (ou pelo GeForce Experience / NVIDIA App).
2. Reinicie o PC.
3. Confira: `nvidia-smi` deve listar as GPUs e mostrar "CUDA Version: 12.x" ou superior.

> Não é preciso instalar o CUDA Toolkit: o PyTorch traz as bibliotecas CUDA dele, e as do faster-whisper vêm via pip (passo 5).

## 2. Python, Git e FFmpeg

```powershell
winget install Python.Python.3.12
winget install Git.Git
winget install Gyan.FFmpeg
```

Feche e reabra o terminal; confira com `py -3.12 --version`, `git --version` e `ffmpeg -version`.

> Use Python **3.11, 3.12 ou 3.13**: algumas bibliotecas de GPU (PyTorch, CTranslate2) costumam demorar a publicar pacotes para a versão mais nova do Python.

## 3. Projeto e ambiente virtual

```powershell
git clone https://github.com/macckk/yt-thumbnail.git
cd yt-thumbnail
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
```

Se o PowerShell bloquear o `Activate.ps1`: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 4. PyTorch com CUDA e dependências de GPU

Instale o PyTorch **antes** do resto, pelo índice oficial com CUDA 12 (veja o comando atual em <https://pytorch.org/get-started/locally/>):

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -e ".[gpu,dev]"
```

Confira: `python -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"` → `True 2`.

## 5. Bibliotecas CUDA do faster-whisper

O faster-whisper (CTranslate2) precisa de cuBLAS e cuDNN para CUDA 12:

```powershell
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
```

Alternativa: baixar as DLLs do pacote do Purfview (<https://github.com/Purfview/whisper-standalone-win/releases>) e colocá-las numa pasta do `PATH`. Detalhes em [solucao-de-problemas.md](solucao-de-problemas.md#cuda-e-cudnn).

## 6. Claude Code

Instale o Claude Code (<https://claude.com/claude-code>), rode `claude` uma vez para fazer login e confira com `claude --version`.

## 7. Fontes

```powershell
pip install fonttools
python scripts/baixar_fontes.py
```

As fontes (licença OFL) vão para `assets/fonts/` junto com os arquivos de licença.

## 8. Configuração

```powershell
copy config.example.yaml config.yaml
copy .env.example .env
```

Edite `config.yaml` (ver [configuracao.md](configuracao.md)) e valide:

```powershell
yt-thumbnail validar
```

## 9. Verificação final

```powershell
yt-thumbnail ambiente
```

Todos os itens devem aparecer como **OK** (2 GPUs, CUDA, FFmpeg, yt-dlp, Claude Code e fontes). O mesmo teste existe como script: `python scripts/check_env.py`.

## Linux

Deve funcionar com os mesmos passos (driver NVIDIA da distro, `python3 -m venv`, `ffmpeg` do gerenciador de pacotes), mas não é testado.
