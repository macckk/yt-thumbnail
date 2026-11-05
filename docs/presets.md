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

## Camada de análise

Usada por `yt-thumbnail analisar`. O prompt é o template `prompts/analise.md` com estes campos do preset:

| Chave | Vira no prompt |
|---|---|
| `analise.tom` | "Tom do título" |
| `analise.titulo_palavras` | "entre N e M palavras" — e é **validado**: título fora da faixa é recusado e o modelo tenta de novo |
| `analise.proibido` | lista de temas/abordagens proibidos |
| `analise.diretrizes_imagem` | o que a cena deve ter (luz, natureza, pessoas de costas...) |
| `imagem.simbolos` | `neutro` pede para evitar símbolos de uma religião específica |

O `estilo_sufixo` e o `negative_prompt` **não** vão para o Claude: são somados ao `prompt_imagem` pelo programa na geração da imagem (Fase 4).

### Variedade das cenas

O template pede que a cena venha **do conteúdo do vídeo** (um objeto, uma metáfora, uma história citada) e não de uma paisagem genérica, e que figura humana apareça só quando for essencial. Sem isso, as diretrizes do preset tendem a produzir sempre "pessoa de costas no campo ao amanhecer". Para mudar o repertório visual de um preset, edite `analise.diretrizes_imagem`.

### Editar o template

`prompts/analise.md` é texto livre em Markdown. Os marcadores entre chaves são substituídos: `{tipo}`, `{titulo}`, `{descricao}`, `{transcricao}`, `{preset}`, `{tom}`, `{titulo_min}`, `{titulo_max}`, `{proibido}`, `{diretrizes_imagem}`, `{simbolos}`. Outras chaves (como o exemplo de JSON) ficam como estão. Mantenha o formato de resposta: os campos do JSON são validados. Para usar outro arquivo, defina `analise.template`.

Os detalhes das camadas de imagem e tipografia serão documentados nas fases 4 e 5.
