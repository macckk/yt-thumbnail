# SPDX-License-Identifier: GPL-3.0-or-later
"""Fase 5 — composição do título sobre as imagens de fundo (Pillow).

Para cada ``base_N.png`` de um vídeo: escreve o ``titulo_capa`` da análise na região indicada
por ``posicao_texto`` (dentro da área segura do preset), com tamanho de fonte automático,
quebra em até ``linhas_max`` linhas, cor escura ou clara conforme o brilho do fundo, véu
translúcido e sombra suave. Grava ``capa_N.jpg`` (< 2 MB), a miniatura de verificação
``mini_N.jpg`` (320×180 / 180×320) e ``capas.json``.
"""

from __future__ import annotations

import io
import itertools
import json
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat
from pydantic import BaseModel, ValidationError

from yt_thumbnail.analise.base import ler_analise
from yt_thumbnail.estado import ORDEM, Estado
from yt_thumbnail.imagem import ler_imagens
from yt_thumbnail.playlist import ler_meta, pasta_video
from yt_thumbnail.presets import Layout, Preset, Tipografia

LIMITE_BYTES = 2 * 1024 * 1024
"""Limite do YouTube para a capa (2 MB)."""

MINIATURA = {"longo": (320, 180), "short": (180, 320)}
CONTRASTE_MINIMO = 3.0
"""Contraste mínimo (WCAG, texto grande) entre o título e o fundo logo atrás dele."""
FONTE_MINIMA_MINIATURA = 14
"""Altura mínima da fonte, em pixels, na miniatura de verificação."""

Fonte = ImageFont.FreeTypeFont | ImageFont.TransposedFont
AbrirFonte = Callable[[int], Fonte]


class ErroComposicao(Exception):
    """Erro de composição que impede o lote (ex.: fonte ausente)."""


class Capa(BaseModel):
    """Uma capa composta."""

    arquivo: str
    miniatura: str
    base: str
    tamanho_fonte: int
    linhas: list[str]
    cor: str
    contraste: float
    opacidade_veu: float
    qualidade: int
    bytes: int
    avisos: list[str] = []


class ArquivoCapas(BaseModel):
    """Conteúdo de ``capas.json``."""

    titulo: str
    posicao: str
    tipo: str
    fonte: str
    capas: list[Capa]
    composto_em: str


@dataclass
class ResultadoComposicao:
    """Resumo de :func:`compor_job`."""

    feitos: dict[str, ArquivoCapas] = field(default_factory=dict)
    existentes: list[str] = field(default_factory=list)
    erros: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Regiao:
    """Retângulo (em pixels) onde o título deve caber e como alinhá-lo."""

    x0: int
    y0: int
    x1: int
    y1: int
    alinhamento: str  # esquerda | direita | centro
    encostar: str | None = None  # borda de onde o véu nasce: esquerda | direita | topo

    @property
    def largura(self) -> int:
        return self.x1 - self.x0

    @property
    def altura(self) -> int:
        return self.y1 - self.y0


# --------------------------------------------------------------------------- fontes


def _abridor(caminho: Path) -> AbrirFonte:
    cache: dict[int, Fonte] = {}

    def abrir(tamanho: int) -> Fonte:
        if tamanho not in cache:
            cache[tamanho] = ImageFont.truetype(str(caminho), tamanho)
        return cache[tamanho]

    return abrir


def abrir_fonte_do_preset(tipografia: Tipografia, raiz: Path) -> tuple[AbrirFonte, str]:
    """Devolve uma função ``tamanho -> fonte`` e o nome do arquivo usado.

    Usa ``fonte``; se o arquivo não existir, ``fonte_alternativa``. Caminhos relativos são
    resolvidos a partir de ``raiz`` (a pasta do config.yaml).
    """
    candidatos = [tipografia.fonte, tipografia.fonte_alternativa]
    for c in candidatos:
        if c is None:
            continue
        caminho = c if c.is_absolute() else raiz / c
        if caminho.is_file():
            return _abridor(caminho), caminho.name
    nomes = ", ".join(str(c) for c in candidatos if c is not None)
    raise ErroComposicao(
        f"Fonte do preset não encontrada ({nomes}). Rode `python scripts/baixar_fontes.py`."
    )


# --------------------------------------------------------------------------- layout


def regiao_texto(tipo: str, posicao: str, tamanho: tuple[int, int], layout: Layout) -> Regiao:
    """Região do título dentro da área segura.

    - Short: dentro da área segura do preset (o quadrado central, que continua visível quando
      o YouTube recorta a capa), centralizado. ``centro`` usa a faixa do meio; as outras
      posições usam os 40% de cima da área, acima do assunto (o prompt de imagem de Shorts
      põe o assunto no centro).
    - Longo ``esquerda``: 58% da área segura, à esquerda, alinhado à esquerda.
    - Longo ``direita``: 58% da área segura, à direita, só na parte de cima (até 62% da altura)
      para não cobrir o canto inferior direito, onde o YouTube mostra a duração.
    - Longo ``topo``: faixa de cima (42% da altura da área segura), centralizado.
    - Longo ``centro``: 76% central da área segura, centralizado.
    """
    w, h = tamanho
    ax0, ay0, ax1, ay1 = layout.area_segura
    x0, y0, x1, y1 = round(ax0 * w), round(ay0 * h), round(ax1 * w), round(ay1 * h)
    sw, sh = x1 - x0, y1 - y0
    if tipo == "short":
        if posicao == "centro":
            meio = y0 + sh // 2
            return Regiao(x0, meio - round(0.2 * sh), x1, meio + round(0.2 * sh), "centro")
        return Regiao(x0, y0, x1, y0 + round(0.4 * sh), "centro")
    if posicao == "esquerda":
        return Regiao(x0, y0, x0 + round(0.58 * sw), y1, "esquerda", "esquerda")
    if posicao == "direita":
        return Regiao(x1 - round(0.58 * sw), y0, x1, y0 + round(0.62 * sh), "direita", "direita")
    if posicao == "topo":
        return Regiao(x0, y0, x1, y0 + round(0.42 * sh), "centro", "topo")
    margem = round(0.12 * sw)
    return Regiao(x0 + margem, y0, x1 - margem, y1, "centro")


def _altura_linha(fonte: Fonte) -> int:
    ascent, descent = fonte.getmetrics()
    return ascent + descent


def _espaco(tamanho: int) -> int:
    return round(tamanho * 0.08)


def quebrar(palavras: list[str], linhas: int, fonte: Fonte) -> list[str]:
    """Divide as palavras em ``linhas`` linhas com a maior linha o mais curta possível."""
    n = len(palavras)
    linhas = min(linhas, n)
    melhor: list[str] = [" ".join(palavras)]
    melhor_largura = float("inf")
    for cortes in itertools.combinations(range(1, n), linhas - 1):
        limites = (0, *cortes, n)
        partes = [" ".join(palavras[a:b]) for a, b in itertools.pairwise(limites)]
        largura = max(fonte.getlength(p) for p in partes)
        if largura < melhor_largura - 0.5:
            melhor, melhor_largura = partes, largura
    return melhor


def ajustar_texto(
    titulo: str,
    regiao: Regiao,
    abrir: AbrirFonte,
    linhas_max: int,
    tamanho_max: int,
    tamanho_min: int,
) -> tuple[int, list[str], bool]:
    """Maior fonte (de ``tamanho_max`` para baixo) em que o título cabe na região.

    Devolve ``(tamanho, linhas, coube)``. Se nem ``tamanho_min`` couber, usa ``tamanho_min``
    com a melhor quebra e ``coube=False``.
    """
    palavras = titulo.split()
    tamanho = tamanho_max
    while tamanho >= tamanho_min:
        fonte = abrir(tamanho)
        alt = _altura_linha(fonte)
        for k in range(1, min(linhas_max, len(palavras)) + 1):
            if k * alt + (k - 1) * _espaco(tamanho) > regiao.altura:
                break
            partes = quebrar(palavras, k, fonte)
            if max(fonte.getlength(p) for p in partes) <= regiao.largura:
                return tamanho, partes, True
        tamanho -= 2
    fonte = abrir(tamanho_min)
    return tamanho_min, quebrar(palavras, linhas_max, fonte), False


def _limites_tamanho(tipo: str, altura: int) -> tuple[int, int]:
    """(máximo, mínimo) do tamanho da fonte, proporcionais à altura da capa."""
    if tipo == "short":
        return round(altura * 0.075), round(altura * 0.03)
    return round(altura * 0.16), round(altura * 0.075)


# --------------------------------------------------------------------------- cor e contraste


def _hex_rgb(cor: str) -> tuple[int, int, int]:
    return int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)


def luminancia(rgb: Iterable[float]) -> float:
    """Luminância relativa (WCAG) de uma cor RGB 0–255."""

    def canal(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (canal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: Iterable[float], b: Iterable[float]) -> float:
    """Razão de contraste WCAG entre duas cores (1 a 21)."""
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _cor_media(imagem: Image.Image, caixa: tuple[int, int, int, int]) -> tuple[float, ...]:
    return tuple(ImageStat.Stat(imagem.crop(caixa).convert("RGB")).mean)


# --------------------------------------------------------------------------- desenho


@dataclass
class _Bloco:
    tamanho: int
    linhas: list[str]
    posicoes: list[tuple[int, int]]  # âncora de cada linha
    ancora: str
    caixa: tuple[int, int, int, int]


def _posicionar(regiao: Regiao, fonte: Fonte, tamanho: int, linhas: list[str]) -> _Bloco:
    alt = _altura_linha(fonte)
    esp = _espaco(tamanho)
    total = len(linhas) * alt + (len(linhas) - 1) * esp
    y = regiao.y0 + (regiao.altura - total) // 2
    larguras = [round(fonte.getlength(linha)) for linha in linhas]
    maior = max(larguras)
    if regiao.alinhamento == "esquerda":
        x, ancora, bx0 = regiao.x0, "la", regiao.x0
    elif regiao.alinhamento == "direita":
        x, ancora, bx0 = regiao.x1, "ra", regiao.x1 - maior
    else:
        x = (regiao.x0 + regiao.x1) // 2
        ancora, bx0 = "ma", x - maior // 2
    posicoes = [(x, y + i * (alt + esp)) for i in range(len(linhas))]
    return _Bloco(tamanho, linhas, posicoes, ancora, (bx0, y, bx0 + maior, y + total))


def _mascara_veu(
    tamanho_img: tuple[int, int], bloco: _Bloco, regiao: Regiao, tipo_veu: str
) -> Image.Image:
    w, h = tamanho_img
    pad = round(bloco.tamanho * 0.7)
    x0, y0, x1, y1 = bloco.caixa
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    if regiao.encostar == "esquerda":
        x0 = -pad
    elif regiao.encostar == "direita":
        x1 = w + pad
    elif regiao.encostar == "topo":
        y0 = -pad
    mascara = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((x0, y0, x1, y1), radius=pad, fill=255)
    raio = pad if tipo_veu == "gradiente" else max(2, pad // 8)
    return mascara.filter(ImageFilter.GaussianBlur(raio))


def _aplicar_veu(
    img: Image.Image, mascara: Image.Image | None, cor: str, opacidade: float
) -> Image.Image:
    if mascara is None or opacidade <= 0:
        return img
    m = mascara.point(lambda v: round(v * opacidade))
    return Image.composite(Image.new("RGB", img.size, cor), img, m)


def _desenhar(
    img: Image.Image,
    bloco: _Bloco,
    fonte: Fonte,
    tip: Tipografia,
    texto_escuro: bool,
) -> Image.Image:
    """Sombra suave + texto sobre ``img`` (já com o véu)."""
    w, h = img.size
    escala = min(w, h) / 720
    # sombra: brilho claro atrás de texto escuro; sombra escura (deslocada) atrás de texto claro
    if tip.sombra.opacidade > 0:
        camada = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(camada)
        desloc = 0 if texto_escuro else round(2 * escala)
        for linha, (x, y) in zip(bloco.linhas, bloco.posicoes, strict=True):
            d.text((x + desloc, y + desloc), linha, font=fonte, fill=255, anchor=bloco.ancora)
        camada = camada.filter(ImageFilter.GaussianBlur(max(1, round(tip.sombra.blur * escala))))
        camada = camada.point(lambda v: min(255, round(v * tip.sombra.opacidade * 1.6)))
        cor_sombra = "#FFFFFF" if texto_escuro else "#000000"
        img = Image.composite(Image.new("RGB", (w, h), cor_sombra), img, camada)
    cor = tip.cor_escura if texto_escuro else tip.cor_clara
    d = ImageDraw.Draw(img)
    for linha, (x, y) in zip(bloco.linhas, bloco.posicoes, strict=True):
        d.text((x, y), linha, font=fonte, fill=cor, anchor=bloco.ancora)
    return img


def salvar_jpeg(imagem: Image.Image, destino: Path, limite: int = LIMITE_BYTES) -> tuple[int, int]:
    """Salva em JPEG (qualidade 90, baixando de 5 em 5 até caber em ``limite``).

    Devolve ``(qualidade, bytes)``.
    """
    for qualidade in range(90, 49, -5):
        buf = io.BytesIO()
        imagem.save(buf, "JPEG", quality=qualidade, optimize=True, progressive=True)
        if buf.tell() <= limite:
            destino.write_bytes(buf.getvalue())
            return qualidade, buf.tell()
    raise ErroComposicao(f"{destino.name}: não coube em {limite} bytes nem com qualidade 50")


@dataclass
class Composicao:
    """Resultado de :func:`compor_capa` (imagem + métricas)."""

    imagem: Image.Image
    tamanho_fonte: int
    linhas: list[str]
    cor: str
    contraste: float
    opacidade_veu: float
    avisos: list[str]


def compor_capa(
    base: Image.Image,
    titulo: str,
    posicao: str,
    tipo: str,
    preset: Preset,
    abrir: AbrirFonte,
) -> Composicao:
    """Compõe o título sobre uma imagem de fundo."""
    tip = preset.tipografia
    layout = preset.layouts.short if tipo == "short" else preset.layouts.longo
    titulo = unicodedata.normalize("NFC", " ".join(titulo.split()))
    regiao = regiao_texto(tipo, posicao, base.size, layout)
    tmax, tmin = _limites_tamanho(tipo, base.height)
    tamanho, linhas, coube = ajustar_texto(titulo, regiao, abrir, tip.linhas_max, tmax, tmin)
    fonte = abrir(tamanho)
    bloco = _posicionar(regiao, fonte, tamanho, linhas)
    avisos = [] if coube else ["o título não coube na área segura no tamanho mínimo"]

    fundo = _cor_media(base, bloco.caixa)
    escuro_rgb, claro_rgb = _hex_rgb(tip.cor_escura), _hex_rgb(tip.cor_clara)
    texto_escuro = contraste(escuro_rgb, fundo) >= contraste(claro_rgb, fundo)
    cor = tip.cor_escura if texto_escuro else tip.cor_clara

    base_rgb = base.convert("RGB")
    mascara = (
        _mascara_veu(base.size, bloco, regiao, tip.veu.tipo) if tip.veu.tipo != "nenhum" else None
    )
    cor_veu = tip.veu.cor if texto_escuro else tip.cor_escura
    # sobe a opacidade do véu até o contraste com o fundo atrás do texto ficar bom
    opacidade = tip.veu.opacidade if mascara is not None else 0.0
    while True:
        com_veu = _aplicar_veu(base_rgb, mascara, cor_veu, opacidade)
        razao = contraste(_hex_rgb(cor), _cor_media(com_veu, bloco.caixa))
        if razao >= CONTRASTE_MINIMO or mascara is None or opacidade >= 0.85:
            break
        opacidade = min(0.85, round(opacidade + 0.1, 2))
    if razao < CONTRASTE_MINIMO:
        avisos.append(f"contraste baixo ({razao:.1f}:1)")
    img = _desenhar(com_veu, bloco, fonte, tip, texto_escuro)
    return Composicao(img, tamanho, linhas, cor, round(razao, 2), opacidade, avisos)


# --------------------------------------------------------------------------- job


def ler_capas(pasta: Path) -> ArquivoCapas | None:
    """Lê ``capas.json`` se ele e todas as capas existirem e forem mais novos que as imagens."""
    arquivo = pasta / "capas.json"
    if not arquivo.is_file():
        return None
    try:
        dados = ArquivoCapas.model_validate_json(arquivo.read_text(encoding="utf-8"))
    except (ValidationError, ValueError):
        return None
    for c in dados.capas:
        if not (pasta / c.arquivo).is_file() or not (pasta / c.miniatura).is_file():
            return None
    imagens = pasta / "imagens.json"
    if imagens.is_file() and imagens.stat().st_mtime > arquivo.stat().st_mtime:
        return None  # imagens geradas de novo depois da composição
    return dados


def compor_video(
    pasta: Path,
    bases: list[str],
    titulo: str,
    posicao: str,
    tipo: str,
    preset: Preset,
    abrir: AbrirFonte,
    nome_fonte: str,
) -> ArquivoCapas:
    """Compõe todas as variações de um vídeo e grava capas, miniaturas e ``capas.json``."""
    for antigo in [*pasta.glob("capa_*.jpg"), *pasta.glob("mini_*.jpg")]:
        antigo.unlink()
    capas = []
    for i, nome_base in enumerate(bases, start=1):
        with Image.open(pasta / nome_base) as base:
            c = compor_capa(base, titulo, posicao, tipo, preset, abrir)
        arquivo, mini = f"capa_{i}.jpg", f"mini_{i}.jpg"
        qualidade, tamanho = salvar_jpeg(c.imagem, pasta / arquivo)
        miniatura = c.imagem.resize(MINIATURA[tipo], Image.Resampling.LANCZOS)
        miniatura.save(pasta / mini, "JPEG", quality=88, optimize=True)
        avisos = list(c.avisos)
        fonte_mini = c.tamanho_fonte * MINIATURA[tipo][1] / c.imagem.height
        if fonte_mini < FONTE_MINIMA_MINIATURA:
            avisos.append(f"fonte pequena na miniatura ({fonte_mini:.0f} px)")
        capas.append(
            Capa(
                arquivo=arquivo,
                miniatura=mini,
                base=nome_base,
                tamanho_fonte=c.tamanho_fonte,
                linhas=c.linhas,
                cor=c.cor,
                contraste=c.contraste,
                opacidade_veu=c.opacidade_veu,
                qualidade=qualidade,
                bytes=tamanho,
                avisos=avisos,
            )
        )
    dados = ArquivoCapas(
        titulo=titulo,
        posicao=posicao,
        tipo=tipo,
        fonte=nome_fonte,
        capas=capas,
        composto_em=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    (pasta / "capas.json").write_text(
        json.dumps(dados.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return dados


def compor_job(
    *,
    job: str,
    tipos: Iterable[str],
    pasta_saida: Path,
    estado: Estado,
    preset: Preset,
    abrir: AbrirFonte,
    nome_fonte: str,
    ids: Iterable[str] | None = None,
    forcar: bool = False,
    limite: int | None = None,
    ao_progredir: Callable[[str, int, int], None] | None = None,
) -> ResultadoComposicao:
    """Compõe as capas dos vídeos com imagens geradas.

    Idempotente: pula vídeos com ``capas.json`` válido e mais novo que ``imagens.json``.
    Erros ficam no estado do vídeo e o lote continua.
    """
    tipos = set(tipos)
    filtro = set(ids) if ids else None
    resultado = ResultadoComposicao()
    pendentes = []
    for r in estado.listar(job):
        if r.tipo not in tipos or (filtro is not None and r.video_id not in filtro):
            continue
        if ORDEM[r.status] < ORDEM["imagens_geradas"]:
            continue
        pasta = pasta_video(pasta_saida, job, r.video_id)
        if not forcar and ler_capas(pasta) is not None:
            resultado.existentes.append(r.video_id)
            if ORDEM[r.status] < ORDEM["capas_compostas"]:
                estado.registrar(job, r.video_id, "capas_compostas")
            continue
        pendentes.append(r)
    if limite is not None:
        pendentes = pendentes[:limite]
    for i, r in enumerate(pendentes, start=1):
        if ao_progredir:
            ao_progredir(r.video_id, i, len(pendentes))
        pasta = pasta_video(pasta_saida, job, r.video_id)
        meta, analise = ler_meta(pasta), ler_analise(pasta)
        imagens = ler_imagens(pasta, 1)
        if meta is None or analise is None or imagens is None:
            msg = "meta.json, analise.json ou imagens ausentes; rode `analisar` e `gerar` antes"
            estado.marcar_erro(job, r.video_id, "compor", msg)
            resultado.erros[r.video_id] = msg
            continue
        try:
            dados = compor_video(
                pasta,
                imagens.arquivos,
                analise.titulo_capa,
                analise.posicao_texto,
                meta.tipo,
                preset,
                abrir,
                nome_fonte,
            )
        except (OSError, ErroComposicao) as e:
            msg = str(e).strip() or e.__class__.__name__
            estado.marcar_erro(job, r.video_id, "compor", msg)
            resultado.erros[r.video_id] = msg
            continue
        estado.registrar(
            job,
            r.video_id,
            "capas_compostas",
            dados={"avisos": sorted({a for c in dados.capas for a in c.avisos})},
            permitir_regredir=forcar,
        )
        resultado.feitos[r.video_id] = dados
    return resultado
