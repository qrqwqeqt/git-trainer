# syntax=docker/dockerfile:1.7
#
# Git Trainer sandbox image.
#
# SECURITY (див. CLAUDE.md → Security Rules):
#   * Контейнер запускається з network="none" — це enforce-иться у
#     SandboxManager під час run, не в Dockerfile.
#   * Працює під непривілейованим користувачем sandbox (UID 1000).
#   * Мінімум пакетів: git + tini. Жодних SSH-ключів, токенів,
#     credentials усередині образу.
#   * Жодних інструментів для виходу за межі контейнера (curl, wget, ssh).

FROM alpine:3.20

RUN apk add --no-cache git tini \
    && addgroup -g 1000 sandbox \
    && adduser -D -u 1000 -G sandbox -h /home/sandbox -s /bin/sh sandbox \
    && mkdir -p /repo \
    && chown sandbox:sandbox /repo

USER sandbox
WORKDIR /repo

# Sane defaults — щоб `git commit` працював без per-container setup.
# user.email/user.name можна перевизначити з API під конкретного студента.
RUN git config --global user.email "student@git-trainer.local" \
    && git config --global user.name "Student" \
    && git config --global init.defaultBranch main \
    && git config --global advice.detachedHead false \
    && git config --global core.pager cat

# Контейнер має «жити», щоб backend міг робити docker exec у нього.
# tini як PID 1 — коректна обробка SIGTERM від `docker stop` та reaping зомбі.
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["sleep", "infinity"]
