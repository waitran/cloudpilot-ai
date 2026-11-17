# Отчёт по этапу 1

Работа выполнена после публикации этапа 0 в private-репозитории
[waitran/cloudpilot-ai](https://github.com/waitran/cloudpilot-ai).
Коммит этапа 0: `e87c3b42c9101e6b8b96009b1efab364013158b4`;
[CI этапа 0](https://github.com/waitran/cloudpilot-ai/actions/runs/44172959564) — success.
Исходный локальный коммит `e128454` сохранён в ветке `stage-0-local-original`.

## Реализовано

- Модульный FastAPI backend: liveness, readiness, system/info, Swagger/OpenAPI.
- Централизованные Pydantic Settings, явный CORS, проверка production-настроек,
  безопасные ответы об ошибках, request ID, lifecycle и закрытие пула соединений.
- SQLAlchemy 2 + psycopg 3, PostgreSQL, базовая пустая миграция Alembic.
  Искусственных бизнес-таблиц нет.
- React/TypeScript/Vite/Tailwind, адаптивная тёмная тема, навигация на шесть страниц.
  Overview и Settings используют реальные ответы API; будущие модули имеют honest empty states.
- Единый API-клиент с deadline и проверкой ответа, TanStack Query, loading/error/retry.
- Compose, отдельные multi-stage Dockerfile, non-root backend/frontend, health checks,
  loopback host-порты, изолированная сеть, volume БД, одноразовый migrate.
- Lock-файлы, Makefile, реальные тесты и CI с backend/frontend/container jobs.

## Проверено локально

| Проверка | Результат |
| --- | --- |
| Backend | 24 pytest-теста с настоящим PostgreSQL 14.24, включая отдельную тестовую БД |
| Миграции | upgrade head, downgrade base, повторный upgrade; alembic_version проверена SQL-запросом |
| Frontend | 8 тестов Vitest/RTL; ESLint, Prettier, TypeScript strict и production build |
| Репозиторий | 5 регрессионных тестов checker; проверка структуры и известных признаков секретов |
| HTTP | Backend live/ready/info, Swagger, OpenAPI, frontend HTML, same-origin API proxy, SPA route |
| Настоящий отказ БД | При остановке PostgreSQL: readiness 503, liveness 200, info показывает unavailable |
| Восстановление БД | После старта PostgreSQL readiness возвращается к 200 |
| Compose | config --quiet проходит |

Backend/frontend/PostgreSQL были запущены вместе в изолированной сессии исполнения.
Между отдельными командами этой среды loopback не общий. Встроенный браузер не смог
подключиться к этому запуску: визуальная проверка через него не подтверждена.
HTML/proxy проверены реальными HTTP-запросами; поведение React — RTL.

Локальный Docker daemon недоступен текущему процессу. Попытка rootless-запуска также
упёрлась в отсутствие uidmap; системные права и настройки не менялись.
Локальные Docker-сборки и Compose up поэтому не заявляются успешными.
Их проверяет job containers на GitHub-hosted runner; итог удалённого CI уточняется
по коммиту реализации после публикации.

## Версии

Python 3.12.16; Node.js 24.22.3; npm 12.2.2; uv 0.13.8.
FastAPI 0.163.2, Pydantic 2.14.3, SQLAlchemy 2.0.58, psycopg 3.3.9,
Alembic 1.20.1, httpx2 2.16.2, pytest 9.2.0, Ruff 0.17.5.
React 19.3.1, TypeScript 5.9.3, Vite 8.3.8, Tailwind 4.3.5,
React Router 7.18.5, TanStack Query 5.108.0, Vitest 5.1.0, ESLint 10.15.0.
Источники точных версий — lock-файлы; PostgreSQL 17 выбран для Compose/CI.

## Безопасность и оставшиеся ограничения

Секреты генерируются в игнорируемом `.env`, имеют приватные права и не печатаются.
Production-режим требует явных HTTPS origins, длинного DB password и проверяемого TLS,
но полноценная авторизация намеренно не реализована: приложение предназначено для локальной работы.

Полный npm audit обнаружил advisory высокой важности в цепочке dev-зависимостей
`picomatch` (ReDoS на недоверенных glob-patterns).
[GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf)
на момент проверки не указывает исправленного релиза (затронуты версии <= 4.0.7).
Не выполнялся принудительный downgrade Vite до старого стека ради изменения числа предупреждений.
Не принимать glob-patterns от недоверенного пользователя; dev server доступен только на loopback.
Frontend runtime поставляется статическими файлами из Nginx; dev-зависимости в runtime-образ не копируются.
Заключительные аудиты: npm runtime — 0 уязвимостей; весь dev-стек — 12 high, 0 critical.
pip-audit для установленных Python-зависимостей не нашёл известных уязвимостей;
собственный editable-пакет исключён из проверки PyPI, его код проверяется тестами и ревью.

Следующие действия: получить обычный доступ к Docker daemon для запуска на своём компьютере;
следить за исправлением advisory dev-цепочки. Затем этап 2: read-only сбор/нормализация метрик,
контракты снимков с единицами, временем и происхождением данных. Этап 2 не реализуется здесь.
