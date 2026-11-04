# SPDX-License-Identifier: GPL-3.0-or-later
"""Baixa as fontes OFL usadas pelos presets (Google Fonts, repositório oficial no GitHub).

Uso: ``python scripts/baixar_fontes.py [--forcar]``

As fontes de peso variável são instanciadas no peso Light (300) com fontTools, se
disponível; senão o arquivo variável é salvo como está (o Pillow usa o peso padrão).
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "assets" / "fonts"
BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl"

# destino -> (pasta no repositório google/fonts, arquivo variável, peso)
FONTES: dict[str, tuple[str, str, int]] = {
    "CormorantGaramond-Light.ttf": ("cormorantgaramond", "CormorantGaramond[wght].ttf", 300),
    "CormorantGaramond-Regular.ttf": ("cormorantgaramond", "CormorantGaramond[wght].ttf", 400),
    "Raleway-Light.ttf": ("raleway", "Raleway[wght].ttf", 300),
    "JosefinSans-Light.ttf": ("josefinsans", "JosefinSans[wght].ttf", 300),
}
LICENCAS = {
    "cormorantgaramond": "OFL-CormorantGaramond.txt",
    "raleway": "OFL-Raleway.txt",
    "josefinsans": "OFL-JosefinSans.txt",
}


def _baixar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "yt-thumbnail-fontes"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - URL fixa
        return r.read()


def _instanciar(dados: bytes, peso: int) -> bytes:
    try:
        from io import BytesIO

        from fontTools.ttLib import TTFont
        from fontTools.varLib.instancer import instantiateVariableFont
    except ImportError:
        print(
            "  (fontTools ausente: salvando a fonte variável; "
            "`pip install fonttools` para fixar o peso)"
        )
        return dados
    fonte = TTFont(BytesIO(dados))
    if "fvar" not in fonte:
        return dados
    inst = instantiateVariableFont(fonte, {"wght": peso})
    saida = BytesIO()
    inst.save(saida)
    return saida.getvalue()


def main() -> int:
    """Baixa fontes e licenças para ``assets/fonts``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forcar", action="store_true", help="baixa de novo mesmo se já existir")
    args = parser.parse_args()
    PASTA.mkdir(parents=True, exist_ok=True)
    cache: dict[str, bytes] = {}
    for destino, (familia, arquivo, peso) in FONTES.items():
        alvo = PASTA / destino
        if alvo.exists() and not args.forcar:
            print(f"ok   {destino} (já existe)")
            continue
        url = f"{BASE}/{familia}/{urllib.request.quote(arquivo)}"
        if url not in cache:
            print(f"get  {url}")
            cache[url] = _baixar(url)
        alvo.write_bytes(_instanciar(cache[url], peso))
        print(f"ok   {destino}")
    for familia, nome in LICENCAS.items():
        alvo = PASTA / nome
        if alvo.exists() and not args.forcar:
            continue
        alvo.write_bytes(_baixar(f"{BASE}/{familia}/OFL.txt"))
        print(f"ok   {nome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
