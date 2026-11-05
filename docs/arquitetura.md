# Arquitetura

> Documento em construção: cada fase acrescenta a sua parte (ver `PLANO.md`).

## Fluxo

```
playlist (yt-dlp) ─► listar ─► transcrever ─► analisar ─► gerar ─► compor ─► revisar ─► aprovar ─► enviar
                     Fase 1     Fase 2         Fase 3      Fase 4   Fase 5    Fase 6               Fase 7
```

Cada etapa lê os artefatos da anterior em `saida/<job>/<video_id>/` e atualiza o estado do vídeo.

## Estados

```
listado → transcrito → analisado → imagens_geradas → capas_compostas → aprovado → enviado
                                                                       ↘ rejeitado
                                                            aprovado → nao_elegivel (Short em canal sem capa personalizada)
```

O estado fica em `saida/estado.db` (SQLite, módulo `estado.py`), uma linha por `(job, video_id)`:

| Coluna | Descrição |
|---|---|
| `status` | último estado alcançado; **só avança** (exceto com `--forcar`) |
| `tipo` | `longo` ou `short` |
| `erro`, `mensagem`, `tentativas` | última etapa que falhou, a mensagem e quantas vezes falhou; limpos quando a etapa dá certo |
| `dados` | JSON com informações auxiliares (ex.: `channel_id`, posição na playlist, seeds) |

Um erro **não** muda o status: o vídeo continua onde estava e é tentado de novo na próxima execução.

## Módulos

| Módulo | Papel |
|---|---|
| `config.py` | carga e validação do `config.yaml` (pydantic) |
| `presets.py` | carga e validação dos presets |
| `estado.py` | estado por vídeo (SQLite) |
| `playlist.py` | Fase 1: listagem e detecção de tipo |
| `transcricao.py` | Fase 2: legenda do YouTube e faster-whisper |
| `ambiente.py` | verificação do ambiente |
| `cli.py` | comandos (Typer) |

## Fase 1 — Listagem e detecção de tipo

1. `yt-dlp` com `extract_flat` lista os IDs da playlist (equivale a `yt-dlp --flat-playlist -J`).
2. Para cada ID sem `meta.json` válido, uma chamada de metadados completa (sem download) traz duração, largura/altura, `channel_id`, título, descrição e URL da capa atual.
3. Classificação (`playlist.classificar`):
   - duração > 180 s → **longo**;
   - duração ≤ 180 s e altura > largura → **short**;
   - duração ≤ 180 s e horizontal/quadrado → **longo**;
   - sem dimensões e duração ≤ 180 s → consulta `https://www.youtube.com/shorts/<id>` sem seguir redirecionamento (200 = Short; redirecionamento = não é). `tipo_origem` registra qual regra decidiu.
4. Grava `meta.json` (escrita atômica) e registra `listado`.

Idempotência: com `meta.json` válido, o vídeo não é consultado de novo; só a posição na playlist é atualizada. Um `meta.json` corrompido é refeito.

### `meta.json`

```json
{
  "video_id": "abc123",
  "titulo": "...",
  "descricao": "...",
  "url": "https://www.youtube.com/watch?v=abc123",
  "duracao": 45.0,
  "largura": 1080,
  "altura": 1920,
  "tipo": "short",
  "tipo_origem": "dimensoes",
  "channel_id": "UC...",
  "canal_nome": "...",
  "thumbnail_url": "https://i.ytimg.com/vi/abc123/maxresdefault.jpg",
  "data_publicacao": "2026-01-02",
  "indice_playlist": 3,
  "listado_em": "2026-11-05T20:00:00+00:00"
}
```

## Fase 2 — Transcrição

Para cada vídeo listado cujo tipo está em `tipos` do job (e sem `transcricao.json` válido):

1. **Legenda** (`transcricao.obter_legenda`): uma consulta de metadados mostra as faixas disponíveis; escolhe a primeira que casa com `transcricao.idiomas`, **manual antes de automática**, e baixa só ela em VTT para `legenda.vtt`.
2. **Limpeza** (`limpar_vtt`): remove cabeçalho, `NOTE`, timestamps, tags de tempo/estilo (`<c>`, `<00:00:01.000>`), marcações como `[Música]` e as linhas repetidas que a legenda automática gera (cada bloco repete a linha anterior).
3. **Whisper** (sem legenda, legenda vazia, `--forcar-whisper` ou falha no download da legenda): baixa só o áudio (`bestaudio`), transcreve com `faster-whisper` (`device="cuda"`, `device_index=gpu.transcricao`, `vad_filter=True`) e apaga o áudio (a menos que `manter_audio`). O modelo é carregado uma vez por execução.
4. **Sem fala**: se o texto final tiver menos de 20 letras, `origem = sem_fala` e `transcricao.txt` fica vazio.

No Windows, as DLLs de cuBLAS/cuDNN dos pacotes `nvidia-*-cu12` são registradas com `os.add_dll_directory` antes de carregar o CTranslate2.

### `transcricao.json`

```json
{
  "origem": "legenda_auto",
  "idioma": "pt",
  "caracteres": 41230,
  "palavras": 7120,
  "modelo": null,
  "legenda_erro": null,
  "transcrito_em": "2026-11-05T21:00:00+00:00"
}
```

`origem`: `legenda_manual`, `legenda_auto`, `whisper` ou `sem_fala`. `legenda_erro` explica por que a legenda não foi usada quando o Whisper entrou por falha (ex.: HTTP 429).
