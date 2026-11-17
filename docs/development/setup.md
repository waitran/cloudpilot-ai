# Запуск CloudPilot AI

## Через Docker Compose

Нужны Docker с доступным daemon и Compose v2+. Python 3.12 нужен для генерации локального
окружения; можно использовать `python3`, если это Python 3.10+ для одного init-скрипта.

Из корня проекта:

```bash
python3.12 scripts/init_env.py
docker compose config --quiet
docker compose up --build --wait --wait-timeout 180
```

Либо `make up`. Генератор создаёт приватный `.env` с новым случайным паролем и не меняет
существующий файл. Не коммитьте его. Миграции запускаются одноразовым сервисом `migrate`;
backend ждёт успешного завершения миграций и готовности PostgreSQL.

| Назначение | Адрес по умолчанию |
| --- | --- |
| Frontend | http://127.0.0.1:15173 |
| Backend | http://127.0.0.1:18080 |
| Swagger | http://127.0.0.1:18080/docs |
| OpenAPI | http://127.0.0.1:18080/openapi.json |
| PostgreSQL | Только сеть Compose; host-порта нет |

Host-порты привязаны к loopback. Настройки `FRONTEND_PORT`, `BACKEND_PORT` в `.env`
позволяют избежать конфликтов. Чужие процессы останавливать не нужно.
При смене frontend-порта обновите `CORS_ORIGINS`, если обращаетесь к API напрямую.
Через same-origin proxy CORS вообще не требуется. Переменная `DATABASE_URL` в `.env`
нужна для нативной разработки: в Compose она заменяется внутренним адресом `postgres:5432`.

## Управление

| Команда | Действие |
| --- | --- |
| `make up` | Сборка, миграции, запуск и ожидание health checks |
| `make down` | Остановка; volume PostgreSQL сохраняется |
| `make logs` | Логи приложения |
| `make restart` | Перезапуск backend/frontend |
| `make migrate` | Явный запуск `alembic upgrade head` |
| `make status` | Состояние контейнеров |
| `make smoke` | Реальные HTTP-проверки запущенного приложения |

Сервис `migrate` после успеха имеет состояние Exited (0) — это штатно.
Не удаляйте volume для устранения обычных проблем запуска: там находятся данные.
Не запускайте `docker compose config` без `--quiet` в общедоступном логе: он раскрывает
подставленные переменные окружения.

## Нативная разработка

Нужны Python 3.12, uv 0.13.8, Node.js 24 и npm 12.2.2. Используйте пользовательский
менеджер версий Node и `.nvmrc`; системные Python/Node менять не нужно.
Версии библиотек зафиксированы в `backend/uv.lock` и `frontend/package-lock.json`.

```bash
python3.12 scripts/init_env.py
uv sync --project backend --locked
cd frontend
npm ci
cd ..
```

Нужен работающий PostgreSQL (проверено на 14.24; Compose/CI используют 17).
Создайте БД `cloudpilot` и отдельную `cloudpilot_test` с локальными credentials.
Укажите реальный `DATABASE_URL` в `.env`. Генератор предполагает PostgreSQL на
`127.0.0.1:15432`; поменяйте адрес при другой установке.

В первом терминале:

```bash
cd backend
uv run alembic upgrade head
uv run uvicorn cloudpilot.main:create_app --factory --host 127.0.0.1 --port 18080
```

Во втором терминале:

```bash
cd frontend
npm run dev
```

Vite проксирует `/api`, `/docs` и `/openapi.json` на `127.0.0.1:18080`.
Для другого backend используйте `API_PROXY_TARGET` при запуске Vite.
Для отдельного origin API можно задать `VITE_API_BASE_URL` на этапе сборки;
в переменные `VITE_*` запрещено помещать секреты — они попадают в JS клиента.

## Проверки

```bash
make check
make test
cd frontend
npm run build
npm audit
npm audit --omit=dev
```

Backend-интеграции требуют `TEST_DATABASE_URL`, указывающий на отдельную БД с именем,
оканчивающимся на `_test`. Они выполняют upgrade/downgrade и не должны использовать рабочую БД.
Без переменной эти два теста явно пропускаются. Пример с URL без пароля — только если ваш
локальный PostgreSQL уже настроен на доверенную локальную аутентификацию:

```bash
TEST_DATABASE_URL=postgresql+psycopg://cloudpilot@127.0.0.1:15432/cloudpilot_test uv run --project backend pytest backend/tests
```

Для конфигурации с паролем передайте URL через закрытое окружение вашего терминала,
не публикуйте его в чатах и логах. В CI все интеграционные тесты обязательны и выполняются
на отдельной PostgreSQL service database.

## Типичные проблемы

- `Docker permission denied`: текущий процесс не имеет доступа к daemon. Проверяйте права
  своего пользователя или используйте предварительно настроенный rootless Docker.
  Не открывайте сокет через `chmod 666`. В этой среде rootless-запуск также ограничен отсутствием uidmap.
- Порт занят: смените host-порт в `.env`; не завершайте чужой процесс.
- Readiness 503: PostgreSQL недоступен. Liveness продолжит отвечать 200; Overview покажет
  проблему подключения. Проверьте credentials и состояние БД.
- Смена пароля в `.env` не меняет пароль уже инициализированного PostgreSQL volume.
  Обновляйте его средствами PostgreSQL, сохраняя данные.
- Ошибка миграции: изучите `docker compose logs migrate`, затем исправьте причину и выполните
  `make migrate`. Не скрывайте ошибку и не продолжайте запуск с неподготовленной схемой.
- В ограниченной среде кеши могут быть read-only: задайте `UV_CACHE_DIR` и `npm_config_cache`
  внутри доступной временной директории. Это не меняет lock-файлы.
- CLI GitHub может иметь истёкшую авторизацию. Для обычного push выполните стандартный
  `gh auth login --hostname github.com --web` в своём терминале; токен в чат не нужен.

Полные результаты и ограничения: [отчёт этапа 1](stage-1-report.md).
