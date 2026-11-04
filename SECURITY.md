# Segurança

## Segredos e tokens

- `secrets/client_secret.json` (OAuth client do Google) e `secrets/tokens/<channel_id>.json` dão acesso aos seus canais. **Nunca** os commite nem compartilhe.
- `config.yaml` e `.env` contêm dados pessoais (IDs de canal, playlists) e também ficam fora do git.
- O `.gitignore` já exclui `secrets/`, `config.yaml`, `.env`, `client_secret*.json`, `token*.json` e `saida/`. Antes de um push, confira com `git status`.
- Se um token vazar: revogue o acesso em <https://myaccount.google.com/permissions> e, se for o caso, recrie o OAuth client no Google Cloud Console.

## Reportar uma vulnerabilidade

Não abra issue pública. Use o recurso **Security → Report a vulnerability** do repositório no GitHub (aviso privado). Responderemos assim que possível.
