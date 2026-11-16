# Shorts

O yt-thumbnail gera capas também para Shorts (1080×1920, título no quadrado central), mas **o envio depende do canal**.

## Quem pode trocar a capa de um Short

O YouTube só aceita capa personalizada em Shorts para alguns canais (em geral, os do **Programa de Parcerias do YouTube**, YPP). Para os demais, a API responde **403** e a capa do Short continua sendo um quadro do vídeo escolhido no app do YouTube.

Por isso cada canal tem, no `config.yaml`:

```yaml
canais:
  espiritual-principal:
    channel_id: UC...
    shorts_capa_personalizada: false   # true só se o canal pode trocar a capa de Shorts
```

| `shorts_capa_personalizada` | O que `enviar` faz com um Short aprovado |
|---|---|
| `false` (padrão) | não tenta enviar; marca `nao_elegivel` e lista no resumo (não é erro) |
| `true` | envia; se a API responder 403, marca `nao_elegivel` com a mensagem da API |

## Vale a pena gerar capas de Shorts?

Mesmo sem poder enviar, a capa gerada serve de referência para escolher o quadro no app ou para reaproveitar em outras redes. Para não gerar, deixe `short` fora de `tipos` no job:

```yaml
jobs:
  - nome: meditacoes
    tipos: [longo]          # [longo, short] para incluir os Shorts
```

## Como o tipo é detectado

Duração ≤ 180 s **e** vídeo vertical → Short; na falta das dimensões, URL `/shorts/`. Ver [arquitetura.md](arquitetura.md#fase-1--listagem-e-detecção-de-tipo).
