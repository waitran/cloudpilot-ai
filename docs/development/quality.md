# Проверки качества

CI проверяет репозиторий, backend с настоящим PostgreSQL, frontend и контейнерный запуск.
Actions закреплены за SHA; права workflow — только `contents: read`; production deployment отсутствует.

| Job | Проверки |
| --- | --- |
| repository | Структура, конфигурации, Python-синтаксис, Markdown-ссылки, признаки секретов, пять регрессионных тестов checker |
| backend | uv locked install, Ruff lint/format, pytest; PostgreSQL 17 и миграции upgrade/downgrade |
| frontend | npm ci, ESLint, Prettier, TypeScript strict, Vitest/RTL, production build |
| containers | Compose config, обе Docker-сборки, PostgreSQL, миграции, health checks, HTTP/proxy/SPA smoke |

`make check` и `make test` запускают соответствующие локальные проверки.
Для integration нужны отдельная тестовая БД и `TEST_DATABASE_URL`; её имя обязано
заканчиваться на `_test`. В CI переменная обязательна. Skip без переменной не считается
выполненной интеграционной проверкой.

Секреты проверяются эвристически в рабочей копии и отдельно в staged blobs.
Ошибка сообщает имя файла и тип риска, но не значение секрета. Это не доказательство
отсутствия любого секрета и не замена ревью. Тесты проверяют обнаружение секрета,
оставленного в индексе после очистки рабочей копии, и force-added `.env`.

Зависимости приложения закреплены lock-файлами. Новый Starlette использует `httpx2`
в TestClient; dev dependency добавлена вместо подавления предупреждения совместимости.
Alembic настроен с `path_separator = os`.

Аудит npm выполняется отдельно для всего dev-инструментария и для runtime-зависимостей.
Нельзя скрывать advisory, делать `audit fix --force` вслепую или объявлять стек безопасным
на основании успешной сборки. Известное ограничение `picomatch` описано в
[отчёте этапа 1](stage-1-report.md).
