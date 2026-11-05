# SPDX-License-Identifier: GPL-3.0-or-later
"""Fase 4 — geração das imagens de fundo (sem texto) com SDXL na GPU de imagem.

Para cada vídeo analisado: ``N`` variações com seeds diferentes, na resolução nativa do tipo
(1344×768 longo / 768×1344 Short), ajustadas (escala + recorte central) para a saída
configurada. Artefatos: ``base_1..N.png`` e ``imagens.json`` (seeds e parâmetros).
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from PIL import Image
from pydantic import BaseModel, ValidationError

from yt_thumbnail.analise.base import ler_analise
from yt_thumbnail.estado import ORDEM, Estado
from yt_thumbnail.playlist import ler_meta, pasta_video
from yt_thumbnail.presets import Preset


class ParametrosImagem(BaseModel):
    """Parâmetros de uma geração (gravados em ``imagens.json`` para reprodutibilidade)."""

    modelo: str
    prompt: str
    prompt_2: str
    negative_prompt: str
    largura: int
    altura: int
    passos: int
    guidance_scale: float


class ArquivoImagens(ParametrosImagem):
    """Conteúdo de ``imagens.json``."""

    seeds: list[int]
    arquivos: list[str]
    saida: tuple[int, int]
    segundos: float
    gerado_em: str


class Gerador(Protocol):
    """Gera uma imagem a partir dos parâmetros e de uma seed."""

    modelo: str

    def gerar(self, p: ParametrosImagem, seed: int) -> Image.Image:
        """Devolve a imagem na resolução ``p.largura × p.altura``."""
        ...


@dataclass
class ResultadoGeracao:
    """Resumo de :func:`gerar_job`."""

    feitos: dict[str, ArquivoImagens] = field(default_factory=dict)
    existentes: list[str] = field(default_factory=list)
    erros: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- utilidades


def montar_parametros(
    prompt_imagem: str,
    preset: Preset,
    modelo: str,
    tamanho: tuple[int, int],
) -> ParametrosImagem:
    """Monta os parâmetros do SDXL.

    O SDXL tem dois codificadores de texto, cada um com limite de 77 tokens. O primeiro
    recebe só a cena (``prompt_imagem``); o segundo (o maior, que mais pesa no estilo)
    recebe o ``estilo_sufixo`` do preset antes da cena. Assim nem a cena nem o estilo são
    cortados quando a soma passa do limite.
    """
    img = preset.imagem
    cena = prompt_imagem.strip().rstrip(".")
    return ParametrosImagem(
        modelo=modelo,
        prompt=cena,
        prompt_2=f"{img.estilo_sufixo.strip()}, {cena}",
        negative_prompt=img.negative_prompt.strip(),
        largura=tamanho[0],
        altura=tamanho[1],
        passos=img.passos,
        guidance_scale=img.guidance_scale,
    )


def ajustar(imagem: Image.Image, saida: tuple[int, int]) -> Image.Image:
    """Escala para cobrir ``saida`` e recorta o centro (sem distorcer)."""
    largura, altura = saida
    escala = max(largura / imagem.width, altura / imagem.height)
    nova = (round(imagem.width * escala), round(imagem.height * escala))
    redim = imagem.convert("RGB").resize(nova, Image.Resampling.LANCZOS)
    x = (redim.width - largura) // 2
    y = (redim.height - altura) // 2
    return redim.crop((x, y, x + largura, y + altura))


def nova_seed() -> int:
    """Seed aleatória de 31 bits."""
    return secrets.randbelow(2**31 - 1)


def ler_imagens(pasta: Path, variacoes: int) -> ArquivoImagens | None:
    """Lê ``imagens.json`` se ele e as ``variacoes`` imagens existirem."""
    arquivo = pasta / "imagens.json"
    if not arquivo.is_file():
        return None
    try:
        dados = ArquivoImagens.model_validate_json(arquivo.read_text(encoding="utf-8"))
    except (ValidationError, ValueError):
        return None
    if len(dados.arquivos) < variacoes or not all((pasta / a).is_file() for a in dados.arquivos):
        return None
    return dados


# --------------------------------------------------------------------------- SDXL


def _ativar_vae_tiling(pipe: Any) -> None:
    """VAE em blocos (menos VRAM na decodificação); a API mudou entre versões do diffusers."""
    vae = getattr(pipe, "vae", None)
    if vae is not None and hasattr(vae, "enable_tiling"):
        vae.enable_tiling()
    elif hasattr(pipe, "enable_vae_tiling"):
        pipe.enable_vae_tiling()


def _ativar_attention_slicing(pipe: Any) -> None:
    """Atenção fatiada (menos VRAM); usa a API disponível na versão do diffusers."""
    if hasattr(pipe, "enable_attention_slicing"):
        pipe.enable_attention_slicing()
        return
    unet = getattr(pipe, "unet", None)
    if unet is not None and hasattr(unet, "set_attention_slice"):
        unet.set_attention_slice("auto")


class GeradorSDXL:
    """Pipeline SDXL (``diffusers``) em fp16; carregado uma vez, no primeiro uso.

    Numa GPU de 8 GB, UNet (~5 GB) + codificadores de texto (~1,6 GB) não deixam espaço para
    gerar em 1344×768. Com ``gpu_texto`` diferente de ``gpu``, os codificadores ficam na outra
    GPU: os embeddings do prompt são calculados lá e copiados para a GPU de imagem.
    """

    def __init__(
        self,
        modelo: str,
        gpu: int,
        *,
        gpu_texto: int | None = None,
        attention_slicing: bool = False,
        cpu_offload: bool = False,
    ) -> None:
        self.modelo = modelo
        self.gpu = gpu
        self.gpu_texto = gpu if gpu_texto is None else gpu_texto
        self.attention_slicing = attention_slicing
        self.cpu_offload = cpu_offload
        self._pipe: Any = None
        self._pipe_img: Any = None
        """Com GPUs divididas: mesmo UNet/VAE, sem codificadores (execução na GPU de imagem)."""

    @property
    def divide_gpus(self) -> bool:
        """``True`` se os codificadores de texto ficam numa GPU separada."""
        return self.gpu_texto != self.gpu and not self.cpu_offload

    def _carregar(self) -> Any:
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import StableDiffusionXLPipeline

        n = torch.cuda.device_count() if torch.cuda.is_available() else 0
        if n <= max(self.gpu, self.gpu_texto):
            raise RuntimeError(
                f"GPU {max(self.gpu, self.gpu_texto)} não disponível (GPUs encontradas: {n}). "
                "Ajuste gpu.imagem / gpu.texto_sdxl no config.yaml."
            )
        pipe = StableDiffusionXLPipeline.from_pretrained(
            self.modelo,
            torch_dtype=torch.float16,
            variant="fp16",
            use_safetensors=True,
            low_cpu_mem_usage=True,
        )
        if self.cpu_offload:
            pipe.enable_model_cpu_offload(gpu_id=self.gpu)
        elif self.divide_gpus:
            pipe.unet.to(f"cuda:{self.gpu}")
            pipe.vae.to(f"cuda:{self.gpu}")
            pipe.text_encoder.to(f"cuda:{self.gpu_texto}")
            pipe.text_encoder_2.to(f"cuda:{self.gpu_texto}")
            # sem os codificadores, o diffusers executa na GPU do UNet/VAE
            self._pipe_img = StableDiffusionXLPipeline(
                vae=pipe.vae,
                text_encoder=None,
                text_encoder_2=None,
                tokenizer=pipe.tokenizer,
                tokenizer_2=pipe.tokenizer_2,
                unet=pipe.unet,
                scheduler=pipe.scheduler,
            )
        else:
            pipe.to(f"cuda:{self.gpu}")
        _ativar_vae_tiling(pipe)
        if self.attention_slicing:
            _ativar_attention_slicing(pipe)
        pipe.set_progress_bar_config(disable=True)
        if self._pipe_img is not None:
            self._pipe_img.set_progress_bar_config(disable=True)
        self._pipe = pipe
        return pipe

    def gerar(self, p: ParametrosImagem, seed: int) -> Image.Image:
        """Gera uma imagem com a seed indicada."""
        import torch

        pipe = self._carregar()
        gerador = torch.Generator(device=f"cuda:{self.gpu}").manual_seed(seed)
        comuns = {
            "width": p.largura,
            "height": p.altura,
            "num_inference_steps": p.passos,
            "guidance_scale": p.guidance_scale,
            "generator": gerador,
        }
        if not self.divide_gpus:
            resultado = pipe(
                prompt=p.prompt,
                prompt_2=p.prompt_2,
                negative_prompt=p.negative_prompt,
                negative_prompt_2=p.negative_prompt,
                **comuns,
            )
            return resultado.images[0]
        with torch.no_grad():
            emb, emb_neg, pooled, pooled_neg = pipe.encode_prompt(
                prompt=p.prompt,
                prompt_2=p.prompt_2,
                device=torch.device(f"cuda:{self.gpu_texto}"),
                num_images_per_prompt=1,
                do_classifier_free_guidance=True,
                negative_prompt=p.negative_prompt,
                negative_prompt_2=p.negative_prompt,
            )
        destino = torch.device(f"cuda:{self.gpu}")
        resultado = self._pipe_img(
            prompt_embeds=emb.to(destino),
            negative_prompt_embeds=emb_neg.to(destino),
            pooled_prompt_embeds=pooled.to(destino),
            negative_pooled_prompt_embeds=pooled_neg.to(destino),
            **comuns,
        )
        return resultado.images[0]


# --------------------------------------------------------------------------- job


def gerar_video(
    pasta: Path,
    params: ParametrosImagem,
    gerador: Gerador,
    variacoes: int,
    saida: tuple[int, int],
    seeds: list[int] | None = None,
) -> ArquivoImagens:
    """Gera as variações de um vídeo e grava ``base_N.png`` e ``imagens.json``."""
    seeds = list(seeds or [])
    while len(seeds) < variacoes:
        seeds.append(nova_seed())
    seeds = seeds[:variacoes]
    for antigo in pasta.glob("base_*.png"):
        antigo.unlink()
    inicio = time.perf_counter()
    arquivos = []
    for i, seed in enumerate(seeds, start=1):
        img = ajustar(gerador.gerar(params, seed), saida)
        nome = f"base_{i}.png"
        img.save(pasta / nome, optimize=True)
        arquivos.append(nome)
    dados = ArquivoImagens(
        **params.model_dump(),
        seeds=seeds,
        arquivos=arquivos,
        saida=saida,
        segundos=round(time.perf_counter() - inicio, 1),
        gerado_em=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    (pasta / "imagens.json").write_text(
        json.dumps(dados.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return dados


def gerar_job(
    *,
    job: str,
    tipos: Iterable[str],
    pasta_saida: Path,
    estado: Estado,
    gerador: Gerador,
    preset: Preset,
    formatos: dict[str, tuple[tuple[int, int], tuple[int, int]]],
    variacoes: int = 3,
    ids: Iterable[str] | None = None,
    forcar: bool = False,
    limite: int | None = None,
    ao_progredir: Callable[[str, int, int], None] | None = None,
) -> ResultadoGeracao:
    """Gera as imagens dos vídeos analisados do job.

    ``formatos`` mapeia tipo → (resolução de geração, resolução de saída). Idempotente: pula
    vídeos com ``imagens.json`` e todas as imagens. Uma falha de GPU/memória (``RuntimeError``
    do PyTorch) fica no estado do vídeo e o lote continua.
    """
    tipos = set(tipos)
    filtro = set(ids) if ids else None
    resultado = ResultadoGeracao()
    pendentes = []
    for r in estado.listar(job):
        if r.tipo not in tipos or (filtro is not None and r.video_id not in filtro):
            continue
        if ORDEM[r.status] < ORDEM["analisado"]:
            continue
        pasta = pasta_video(pasta_saida, job, r.video_id)
        if not forcar and ler_imagens(pasta, variacoes) is not None:
            resultado.existentes.append(r.video_id)
            if ORDEM[r.status] < ORDEM["imagens_geradas"]:
                estado.registrar(job, r.video_id, "imagens_geradas")
            continue
        pendentes.append(r)
    if limite is not None:
        pendentes = pendentes[:limite]
    for i, r in enumerate(pendentes, start=1):
        if ao_progredir:
            ao_progredir(r.video_id, i, len(pendentes))
        pasta = pasta_video(pasta_saida, job, r.video_id)
        meta, analise = ler_meta(pasta), ler_analise(pasta)
        if meta is None or analise is None:
            msg = "meta.json ou analise.json ausente; rode `listar` e `analisar` antes"
            estado.marcar_erro(job, r.video_id, "gerar", msg)
            resultado.erros[r.video_id] = msg
            continue
        geracao, saida = formatos[meta.tipo]
        params = montar_parametros(analise.prompt_imagem, preset, gerador.modelo, geracao)
        try:
            dados = gerar_video(pasta, params, gerador, variacoes, saida)
        except Exception as e:  # noqa: BLE001 - não derruba o lote
            msg = str(e).strip().splitlines()[0] if str(e).strip() else e.__class__.__name__
            if "out of memory" in msg.lower():
                msg += " — tente imagem.attention_slicing: true ou imagem.cpu_offload: true"
            estado.marcar_erro(job, r.video_id, "gerar", msg)
            resultado.erros[r.video_id] = msg
            continue
        estado.registrar(
            job,
            r.video_id,
            "imagens_geradas",
            dados={"seeds": dados.seeds},
            permitir_regredir=forcar,
        )
        resultado.feitos[r.video_id] = dados
    return resultado
