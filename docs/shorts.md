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

## Escolher quais Shorts trocam de capa

Para trocar só alguns, abra `yt-thumbnail selecionar --tipo short`: a página mostra a capa atual de cada Short, e os que você marcar ficam com a capa de hoje.

## Backup e restauração

O YouTube só serve a capa atual de um Short em formato horizontal, com a capa no centro e as laterais desfocadas; o backup (`capa_original.jpg`) é essa imagem. O `restaurar` envia a versão vertical (`capa_original_vertical.jpg`): o quadro do vídeo, se o Short não tinha capa personalizada, ou o centro do backup ampliado, se tinha. Ver [uso-cli.md](uso-cli.md#yt-thumbnail-restaurar-id-id---job). Veja o [tutorial](tutorial.md#2-escolher-quais-vídeos-ganham-capa-nova-selecionar).

## Como o tipo é detectado

Duração ≤ 180 s **e** vídeo vertical → Short; na falta das dimensões, URL `/shorts/`. Ver [arquitetura.md](arquitetura.md#fase-1--listagem-e-detecção-de-tipo).
