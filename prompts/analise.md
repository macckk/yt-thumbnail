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

Regras para `prompt_imagem`:
- Em **inglês**, uma descrição visual concreta da cena (assunto, ambiente, luz, enquadramento),
  com 25 a 60 palavras, compatível com a capa {tipo}.
- **Nunca** peça texto, letras, palavras, placas, legendas ou logotipos.
- Pessoas, se houver, de costas, em silhueta ou à distância (sem rostos e mãos em close).
- Deixe uma área limpa e calma (céu, névoa, parede, água) do lado indicado em `posicao_texto`,
  para o título ser escrito depois. Para `short`, mantenha o assunto principal no terço central.
- Não inclua sufixo de estilo genérico (ele é adicionado depois pelo programa).
