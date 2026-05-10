# Git Trainer — Claude Code Configuration

## Project Overview

Інтерактивна багатокористувацька платформа для навчання Git з візуалізацією у реальному часі.
Студенти працюють з ізольованими Git-репозиторіями в Docker і бачать зміни графу гілок миттєво через WebSocket.

**Stack:** Python (FastAPI) · React (Vite) · WebSocket · Docker · PostgreSQL

## Architecture

```
git-trainer/
├── backend/               # FastAPI + WebSocket сервер
│   ├── app/
│   │   ├── main.py        # Entrypoint, CORS, lifecycle
│   │   ├── api/           # REST endpoints (rooms, users, sessions)
│   │   ├── ws/            # WebSocket handlers
│   │   ├── git/           # Git command execution layer
│   │   ├── docker/        # Container management per session
│   │   └── models/        # SQLAlchemy / Pydantic schemas
│   ├── tests/
│   └── requirements.txt
├── frontend/              # React + Vite
│   ├── src/
│   │   ├── components/
│   │   │   ├── GitGraph/  # D3.js або react-flow граф
│   │   │   ├── Terminal/  # Псевдотермінал для команд
│   │   │   └── Room/      # Кімната / список учасників
│   │   ├── hooks/         # useWebSocket, useGitState
│   │   └── store/         # Zustand або Redux стейт
│   └── package.json
├── docker/
│   ├── sandbox/           # Dockerfile для Git-пісочниці
│   └── docker-compose.yml
└── CLAUDE.md
```

## Key Commands

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev          # порт 5173

# Docker
docker compose up --build    # підняти все
docker compose down -v       # зупинити + видалити volumes

# Tests
cd backend && pytest -v
cd frontend && npm test
```

## Core Domain Concepts

- **Room** — ізольована навчальна сесія, має свій Docker-контейнер з Git-репо
- **Session** — підключення одного студента до кімнати через WebSocket
- **GitEvent** — подія (commit, branch, merge тощо), яка транслюється всім у кімнаті
- **Sandbox** — Docker-контейнер з bare Git репозиторієм, доступний тільки через backend API

## WebSocket Protocol

Події передаються як JSON:
```json
{ "type": "GIT_EVENT", "action": "commit", "payload": { "hash": "abc123", "message": "init", "branch": "main" } }
{ "type": "USER_JOINED", "userId": "...", "username": "..." }
{ "type": "GRAPH_UPDATE", "graph": { "nodes": [...], "edges": [...] } }
```

## Security Rules

- Git команди виконуються ТІЛЬКИ всередині Docker sandbox-контейнера
- Ніколи не виконувати shell-команди безпосередньо на хості
- Валідувати всі Git-команди через whitelist перед передачею в контейнер
- Sandbox контейнер не має мережевого доступу (network: none)

## Code Conventions

- Python: type hints обов'язкові, async/await для всіх I/O операцій
- Назви WebSocket handlers: `on_<event>` (наприклад `on_git_command`)
- React компоненти: функціональні, TypeScript, окремий файл для типів
- Git graph state — immutable updates (не мутувати напряму)
- Всі помилки логувати з контекстом (room_id, user_id)

## Environment Variables

```
# backend/.env
DATABASE_URL=postgresql://user:pass@localhost:5432/gittrainer
SECRET_KEY=...
DOCKER_SOCKET=/var/run/docker.sock
SANDBOX_IMAGE=git-trainer-sandbox:latest
MAX_ROOMS=50

# frontend/.env
VITE_WS_URL=ws://localhost:8000/ws
VITE_API_URL=http://localhost:8000
```

## Do Not Touch

- `docker/sandbox/` — змінювати тільки якщо явно попрошено, це security-critical
- Не додавати залежності без оновлення `requirements.txt` / `package.json`
- Не комітити `.env` файли

## Testing Strategy

- Backend unit tests: pytest + httpx (async)
- WebSocket тести: pytest-asyncio + websockets client
- Frontend: Vitest + React Testing Library
- Інтеграційні тести запускати через `docker compose` (тестовий профіль)

## Thesis Context

Проєкт є бакалаврською дипломною роботою (КПІ ім. Ігоря Сікорського, група ІМ-23).
Захист — червень 2026. Пріоритет: робочий MVP + чистота коду для демонстрації.
