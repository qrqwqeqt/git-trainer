# Git Trainer backend — FastAPI + WebSocket.
# Керує sandbox-контейнерами через docker SDK + примонтований docker.sock
# (sibling-контейнери на хост-демоні), тому docker CLI всередині не потрібен.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Спершу залежності — кеш шару не інвалідовується при зміні коду.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
