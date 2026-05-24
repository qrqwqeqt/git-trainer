"""Навантажувальний стенд Git Trainer для Розділу 4 (дослідження).

Піднімає N кімнат × M віртуальних студентів, кожен виконує сценарій git-команд
через WebSocket і вимірює end-to-end латентність (надсилання GIT_COMMAND →
отримання власного GIT_EVENT). Наприкінці друкує перцентилі латентності,
throughput, частку помилок і споживання памʼяті sandbox-ів.

Передумови: backend запущено (uvicorn :8000), Docker daemon живий, образ
git-trainer-sandbox зібрано.

Приклади:
    python -m benchmarks.load_test --rooms 5 --users 4 --commits 10
    python -m benchmarks.load_test --rooms 1 --users 1 --commits 50 --json

Результат можна вставляти у Розділ 4 (таблиця латентності + графік навантаження).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from dataclasses import dataclass, field

import httpx
import websockets


@dataclass
class Sample:
    latency_ms: float
    ok: bool


@dataclass
class Report:
    samples: list[Sample] = field(default_factory=list)
    errors: int = 0

    def add(self, latency_ms: float, ok: bool) -> None:
        self.samples.append(Sample(latency_ms, ok))
        if not ok:
            self.errors += 1


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    rank = max(1, min(len(sorted_vals), math.ceil(p / 100 * len(sorted_vals))))
    return sorted_vals[rank - 1]


async def _send_and_wait(
    ws: websockets.WebSocketClientProtocol,
    user_id: str,
    command: str,
    timeout: float,
) -> bool:
    """Надіслати git-команду і дочекатись власного GIT_EVENT. True якщо exit==0."""
    await ws.send(json.dumps({"type": "GIT_COMMAND", "payload": {"command": command}}))
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        remaining = deadline - time.perf_counter()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            return False
        msg = json.loads(raw)
        # Чужі GIT_EVENT / GRAPH_UPDATE / USER_* — пропускаємо, чекаємо свій.
        if msg.get("type") == "GIT_EVENT" and msg.get("userId") == user_id:
            return int(msg.get("payload", {}).get("exit_code", 1)) == 0
        if msg.get("type") == "ERROR":
            return False
    return False


async def _run_user(
    base_ws: str,
    room: str,
    user_index: int,
    commits: int,
    timeout: float,
    report: Report,
) -> None:
    user_id = f"u{user_index}"
    username = f"student{user_index}"
    url = f"{base_ws}/ws/{room}?user_id={user_id}&username={username}"
    async with websockets.connect(url, max_queue=None) as ws:
        # Warm-up: ініціалізація репо (не вимірюємо — це разова дія кімнати).
        await _send_and_wait(ws, user_id, "git init", timeout)
        for i in range(commits):
            cmd = f"git commit --allow-empty -m c-{user_id}-{i}"
            t0 = time.perf_counter()
            ok = await _send_and_wait(ws, user_id, cmd, timeout)
            report.add((time.perf_counter() - t0) * 1000.0, ok)


async def _fetch_json(base_http: str, path: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{base_http}{path}")
            r.raise_for_status()
            return r.json()
    except Exception as exc:  # noqa: BLE001 — метрики не критичні для бенчмарку
        print(f"  (не вдалося отримати {path}: {exc})")
        return None


async def main() -> None:
    ap = argparse.ArgumentParser(description="Git Trainer load test")
    ap.add_argument("--rooms", type=int, default=3)
    ap.add_argument("--users", type=int, default=2, help="студентів на кімнату")
    ap.add_argument("--commits", type=int, default=10, help="команд на студента")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--timeout", type=float, default=15.0, help="сек на команду")
    ap.add_argument("--prefix", default="load", help="префікс імен кімнат")
    ap.add_argument("--json", action="store_true", help="вивід у JSON")
    args = ap.parse_args()

    # Windows-консоль часто у cp1251 — українські символи валять print.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — не критично, лише вивід
        pass

    base_ws = f"ws://{args.host}:{args.port}"
    base_http = f"http://{args.host}:{args.port}"
    report = Report()

    tasks = [
        _run_user(base_ws, f"{args.prefix}-{r}", u, args.commits, args.timeout, report)
        for r in range(args.rooms)
        for u in range(args.users)
    ]
    total_clients = len(tasks)
    print(
        f"Запуск: {args.rooms} кімнат x {args.users} студентів = {total_clients} "
        f"клієнтів, по {args.commits} команд кожен..."
    )

    wall_start = time.perf_counter()
    await asyncio.gather(*tasks)
    wall_s = time.perf_counter() - wall_start

    mem = await _fetch_json(base_http, "/metrics/sandboxes")
    srv = await _fetch_json(base_http, "/metrics")

    lats = sorted(s.latency_ms for s in report.samples if s.ok)
    n = len(report.samples)
    ok_n = len(lats)
    throughput = n / wall_s if wall_s > 0 else 0.0

    result = {
        "config": {
            "rooms": args.rooms,
            "users_per_room": args.users,
            "commits_per_user": args.commits,
            "total_clients": total_clients,
        },
        "commands_total": n,
        "commands_failed": report.errors,
        "wall_seconds": round(wall_s, 2),
        "throughput_cmd_s": round(throughput, 1),
        "latency_ms": {
            "avg": round(sum(lats) / ok_n, 1) if ok_n else 0.0,
            "p50": round(_pct(lats, 50), 1),
            "p95": round(_pct(lats, 95), 1),
            "p99": round(_pct(lats, 99), 1),
            "max": round(lats[-1], 1) if lats else 0.0,
        },
        "sandbox_memory": mem,
        "server_metrics": srv,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    lat = result["latency_ms"]
    print("\n================ РЕЗУЛЬТАТИ ================")
    print(f"Команд усього:      {n}   (помилок: {report.errors})")
    print(f"Час прогону:        {wall_s:.2f} c")
    print(f"Пропускна здатність:{throughput:8.1f} команд/с")
    print("-- Латентність команди (мс) --")
    print(f"  avg={lat['avg']}  p50={lat['p50']}  p95={lat['p95']}  "
          f"p99={lat['p99']}  max={lat['max']}")
    if mem:
        print(f"-- Памʼять sandbox-ів: {mem['total_mib']} MiB на {mem['count']} "
              f"контейнерів (~{round(mem['total_mib'] / max(mem['count'], 1), 1)} "
              f"MiB/контейнер) --")
    print("===========================================")


if __name__ == "__main__":
    asyncio.run(main())
