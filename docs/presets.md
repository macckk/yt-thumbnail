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

## Camada de imagem

Usada por `yt-thumbnail gerar` (SDXL).

| Chave | Efeito |
|---|---|
| `imagem.estilo_sufixo` | estilo comum a todas as capas do preset (luz, paleta, clima) |
| `imagem.negative_prompt` | o que evitar (texto, letras, logotipos, escuridão, mãos deformadas...) |
| `imagem.guidance_scale` | quanto o SDXL segue o prompt (5–7 costuma ser bom; alto demais satura) |
| `imagem.passos` | passos de difusão (30 é um bom equilíbrio; mais = mais lento) |
| `imagem.paleta` | referência de cores do preset (usada na composição e como guia ao escrever o estilo) |

**Como o prompt é montado.** O SDXL tem dois codificadores de texto, cada um lê no máximo 77 tokens (~50–60 palavras). Para nada importante ser cortado:

- 1º codificador: só a cena (`prompt_imagem` da análise);
- 2º codificador (o maior, que mais pesa no estilo): `estilo_sufixo`, depois a cena.

O `negative_prompt` vai para os dois. Mantenha o `estilo_sufixo` curto (até ~25 palavras): no 2º codificador ele vem antes da cena, e o que passar de 77 tokens é cortado do **fim** da cena. Por isso o template de análise pede que o `prompt_imagem` comece pela composição (enquadramento e lado da área limpa) — a cena completa continua no 1º codificador.

**Requisitos.** Com duas GPUs de 8 GB, o UNet fica numa e os codificadores + VAE na outra (veja `gpu.texto_sdxl` em [configuracao.md](configuracao.md)). ~52 s por imagem em 1344×768 numa RTX 3060 Ti, mais ~10 s de carga por execução.

Os detalhes da camada de tipografia serão documentados na fase 5.
