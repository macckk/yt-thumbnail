# Shorts

O yt-thumbnail gera capas também para Shorts (1080×1920, título no quadrado central), mas **o envio depende do canal**.

## Quem pode trocar a capa de um Short

O YouTube aceita capa personalizada em Shorts, mas a liberação depende do canal (conta verificada e recursos intermediários ativos; a regra já mudou algumas vezes). Se o canal não puder, a API responde **403** e a capa do Short continua sendo um quadro do vídeo escolhido no app do YouTube — o yt-thumbnail marca o vídeo como `nao_elegivel`, sem tratar como erro.

Por isso cada canal tem, no `config.yaml`:

```yaml
canais:
  espiritual-principal:
    channel_id: UC...
    shorts_capa_personalizada: true    # false para nem tentar enviar capa de Short
```

| `shorts_capa_personalizada` | O que `enviar` faz com um Short aprovado |
|---|---|
| `true` (padrão) | envia; se a API responder 403, marca `nao_elegivel` com a mensagem da API |
| `false` | não tenta enviar; marca `nao_elegivel` e lista no resumo (não é erro) |

## Para não gerar capas de Shorts

Mesmo sem poder enviar, a capa gerada serve de referência para escolher o quadro no app ou para reaproveitar em outras redes. Para não gerar, deixe `short` fora de `tipos` no job:

```yaml
jobs:
  - nome: meditacoes
    tipos: [longo]          # [longo, short] para incluir os Shorts
```

## Como o tipo é detectado

Duração ≤ 180 s **e** vídeo vertical → Short; na falta das dimensões, URL `/shorts/`. Ver [arquitetura.md](arquitetura.md#fase-1--listagem-e-detecção-de-tipo).
