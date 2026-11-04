# Presets de identidade visual

Um preset (`presets/<nome>.yaml`) controla três camadas:

| Camada | Chave | Usada por |
|---|---|---|
| Análise | `analise` | Claude: tom, tamanho do título, temas proibidos, diretrizes de cena |
| Imagem | `imagem` | SDXL: sufixo de estilo, prompt negativo, paleta, passos, guidance |
| Tipografia | `tipografia` + `layouts` | Pillow: fonte, cores, sombra, véu, áreas seguras |

O campo `nome` deve ser igual ao nome do arquivo. Chaves desconhecidas são rejeitadas.

## Criar um preset

1. Copie `presets/espiritualidade.yaml` para `presets/<novo>.yaml`.
2. Troque `nome` e ajuste as camadas.
3. Aponte um job para ele (`preset: <novo>`) e rode `yt-thumbnail validar`.

## Referência rápida

- `analise.titulo_palavras`: `[mínimo, máximo]` de palavras do título.
- `imagem.simbolos`: `neutro` (padrão) ou `livre`.
- `imagem.paleta`, `tipografia.cor_*`, `veu.cor`: cores `#RRGGBB`.
- `tipografia.veu.tipo`: `gradiente`, `solido` ou `nenhum`.
- `layouts.<tipo>.area_segura`: `[x0, y0, x1, y1]` em frações (0–1) da imagem.

Os detalhes de cada camada serão documentados nas fases 3 (análise), 4 (imagem) e 5 (tipografia).
