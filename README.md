# Forge ⚡

Production-Grade AI Software Engineer powered by Evidence-Driven Planning & Deterministic AST Verification.

## 🚀 Key Features

- **Issue Understanding**: Parses issues into intent, code symbols, target files, and test suites.
- **Repository Brain**: Zero-token experience recall of past resolved issues via PostgreSQL.
- **Adaptive Evidence Investigator**: Fast parallel evidence gathering (~15ms) with contradiction checking.
- **Evidence-Driven Planner**: Minimal AST context slicing ($\le 2,500$ tokens) & zero-hallucination DB tree verification.
- **Git Worktree Isolation**: Symbol-aware code patching in isolated git worktrees with AST pre-flight safety gates.

## 🛠️ Stack

- **Language**: Python 3.11 (`uv` package manager)
- **API**: FastAPI
- **Parsing**: Tree-sitter AST & Call Graph Resolver
- **Database & Cache**: PostgreSQL, Redis, Qdrant
- **LLMs**: Ollama, Voyage AI, OpenAI

## ⚡ Quickstart

```powershell
# 1. Install dependencies
cd backend
uv sync

# 2. Run migrations
uv run alembic upgrade head

# 3. Run test benchmark suite
uv run pytest
```

## 📜 License

Distributed under the **Apache License 2.0** with Additional Commercial, Attribution & SaaS Restrictions. See [`LICENSE`](LICENSE) for details.
