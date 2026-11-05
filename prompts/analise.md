# Análise para capa de vídeo do YouTube

Você é um diretor de arte criando a capa (thumbnail) de um vídeo do YouTube em português.
Leia os dados do vídeo e a transcrição, entenda a mensagem central e proponha a capa.

## Dados do vídeo
- Tipo: {tipo} (longo = capa horizontal 16:9; short = capa vertical 9:16)
- Título original: {titulo}
- Descrição: {descricao}

## Transcrição
{transcricao}

## Identidade visual (preset "{preset}")
- Tom do título: {tom}
- Título da capa: entre {titulo_min} e {titulo_max} palavras, em português, curto e legível em tamanho pequeno.
  Não repita o título original inteiro; destaque a ideia central ou o benefício para quem assiste.
  Use maiúscula só no início da frase e em nomes próprios (ex.: "Todos somos chamados").
- Proibido: {proibido}
- Diretrizes de imagem: {diretrizes_imagem}
- Símbolos religiosos: {simbolos} (com "neutro", não use cruzes, imagens de santos, Jesus, anjos
  com aparência religiosa ou símbolos de uma religião específica; prefira luz, natureza, velas,
  mãos e paisagens).

## Tarefa
Responda **apenas** com um objeto JSON válido, sem texto antes ou depois, neste formato:

```json
{
  "tema": "tema central em poucas palavras",
  "resumo": "2-3 frases sobre a mensagem do vídeo",
  "gancho": "a ideia que faz a pessoa querer assistir",
  "emocao": "paz | esperança | gratidão | consolo | fé | amor | ...",
  "elementos_visuais": ["elemento 1", "elemento 2", "elemento 3"],
  "titulo_capa": "título curto da capa",
  "prompt_imagem": "prompt em inglês para o Stable Diffusion XL",
  "posicao_texto": "esquerda | direita | topo | centro"
}
```

Como escolher a cena (o mais importante):
- **Parta do conteúdo deste vídeo**, não de uma paisagem genérica. Procure na transcrição uma
  imagem concreta: um objeto, uma metáfora, uma história ou parábola citada, um lugar descrito
  (ex.: uma janela aberta, uma semente brotando, uma ponte, uma lamparina acesa, um barco no
  cais, um caminho com bifurcação, uma muda recém-plantada, uma mesa simples com pão).
- **Evite o clichê** "pessoa de costas num campo/lago ao amanhecer". Use figura humana só quando
  ela for essencial à ideia; muitas capas ficam melhores com um objeto ou um detalhe da natureza.
- **Varie** o enquadramento (plano aberto, plano médio, detalhe em close de um objeto ou planta),
  o ambiente (interior aconchegante, jardim, mar, montanha, cidade pequena, floresta, céu) e a
  hora/luz (manhã, golden hour, luz de vela, dia nublado claro), sempre dentro da paleta clara
  e serena do preset.

Regras para `prompt_imagem`:
- Em **inglês**, uma descrição visual concreta da cena (assunto, ambiente, luz, enquadramento),
  com 25 a 60 palavras, compatível com a capa {tipo}.
- **Nunca** peça texto, letras, palavras, placas, legendas ou logotipos.
- Pessoas, se houver, de costas, em silhueta ou à distância (sem rostos e mãos em close).
- Deixe uma área limpa e calma (céu, névoa, parede, água, fundo desfocado) do lado indicado em
  `posicao_texto`, para o título ser escrito depois. Escolha `posicao_texto` pela composição da
  cena (não use sempre o mesmo lado). Para `short`, mantenha o assunto principal no terço central.
- Não inclua sufixo de estilo genérico (ele é adicionado depois pelo programa).
