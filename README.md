# The AI Counsel

A multi-model deliberation system: several LLMs answer a question independently,
rank each other's answers, and a chairman model synthesizes a final response.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (Python) and Node.js.

```bash
# Backend — http://localhost:8001
uv run python -m backend.main

# Frontend — http://localhost:5173
cd frontend && npm install && npm run dev
```

Or run both at once:

```bash
./start.sh
```

Add your provider API keys (OpenRouter, Google, etc.) in the in-app settings.

## Stack

- **Backend** — FastAPI (Python), with a built-in MCP server at `/mcp/sse`
- **Frontend** — React + Vite
- **Providers** — OpenRouter, Ollama, Groq, direct provider APIs, and custom
  OpenAI-compatible endpoints

## License

MIT — see [LICENSE](LICENSE). Built on the open-source
[the-ai-counsel](https://github.com/jacob-bd/the-ai-counsel) by Jacob Ben David,
extended here as the experimental apparatus for a master's thesis.
