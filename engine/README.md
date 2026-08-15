# chat-compressor (engine)

Python package vendored into the comPREssOR Cursor extension.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests
```

## Hook CLI

```bash
chat-compressor-hook --help
# or
python -m chat_compressor.hook_cli --help
```

Console script entry: `chat-compressor-hook` → `chat_compressor.hook_cli:main`.

## Env

Copy `env.example` for lab knobs. IDE hooks load `~/.cursor/chat-compressor.env` (never put API keys there).
