# Project notes

## API keys
- The OpenRouter key lives in `.env` as `OPENROUTER_API_KEY` (gitignored; template in `.env.example`).
- Always load it from the environment variable. Never hardcode keys, print them, or commit them.
- Enable the secret guard once per clone: `sh scripts/install-hooks.sh`.
- Keep the local file private: `chmod 600 .env`.
