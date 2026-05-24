"""Pytest налаштування: ізольована тестова БД + автоматичний reset схеми.

DATABASE_URL встановлюється на module-рівні до будь-яких імпортів app.*,
щоб get_settings()/get_engine() ловив саме тестовий URL, а не production.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

# Тимчасова SQLite-БД на час pytest-сесії. Файл лежить у tmpdir, видаляється
# atexit-ом. У межах одного процесу буде один engine, схема резетиться перед
# кожним тестом фікстурою `_reset_db` нижче.
_db_dir = Path(tempfile.mkdtemp(prefix="git-trainer-test-"))
_db_path = _db_dir / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_path.as_posix()}"
# Аудит пише в БД з WS-хендлера; під TestClient (portal-loop) це загострює
# проблему "Event loop is closed". Логіку аудиту перевіряємо напряму в
# test_audit.py, тож у WS-смоук-тестах persistence вимикаємо.
os.environ["AUDIT_ENABLED"] = "false"


def _cleanup_tmp_db() -> None:
    shutil.rmtree(_db_dir, ignore_errors=True)


atexit.register(_cleanup_tmp_db)


# Імпорти після того, як env вже встановлено.
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.docker.sandbox import ExecResult  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


@pytest.fixture()
def app():
    return fastapi_app


@pytest.fixture()
def fake_sandbox(monkeypatch):
    """Підміняє sandbox_manager у handlers, щоб тести не торкали Docker daemon.

    За замовчуванням:
      * `exec` повертає вдалий результат для git-status;
      * `get` повертає None — тобто sandbox у кімнаті ще не стартував,
        тож GRAPH_UPDATE-snapshot при connect не пускається.
    Тести, що потребують інакшої поведінки, перевизначають return_value /
    side_effect на отриманому фейку.
    """
    fake = MagicMock()
    fake.start = AsyncMock(return_value=MagicMock())
    fake.exec = AsyncMock(
        return_value=ExecResult(
            exit_code=0, stdout="On branch main\n", stderr=""
        )
    )
    fake.get.return_value = None
    monkeypatch.setattr("app.ws.handlers.sandbox_manager", fake)
    return fake


@pytest_asyncio.fixture(autouse=True)
async def _reset_db():
    """Перед кожним тестом — повний reset схеми (drop_all + create_all)
    + close_db. Без close-у engine, який міг бути створений у portal-loop-і
    попереднього тесту, лишається із закритими aiosqlite-зʼєднаннями;
    наступний тест отримує "Event loop is closed".
    """
    from app.db.session import close_db, get_engine
    from app.models.db import Base

    await close_db()  # скинути engine, створений у попередньому тесті
    engine = get_engine()  # створиться у поточному loop-і
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await close_db()
