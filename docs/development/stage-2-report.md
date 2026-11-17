# Этап 2: Data Collection

Реализованы registry источников, read-only Kubernetes SDK и Prometheus HTTP connectors,
нормализация, CSV resources/metrics/billing, durable PostgreSQL worker, query API,
качество данных, Resources, ResourceDetails и Sources & imports.

## Что проверено локально

- 53 backend-теста, включая PostgreSQL integration, миграцию upgrade/downgrade,
  идемпотентность, billing reconciliation, scope/synthetic isolation, восстановление lease,
  API validation, SDK GET-only обращения, NaN и ошибки Prometheus, quality history/gaps/stale/capacity.
- 15 frontend-тестов: API/status, navigation, filters, empty/error states, details,
  CSV upload/size limit и отдельные валюты/точные суммы.
- 5 проверок repository checker; Ruff lint/format, ESLint, Prettier, TypeScript и Vite build.
- Настоящий HTTP сценарий: PostgreSQL + API + отдельный worker + Vite proxy, CSV загрузки,
  чтение inventory/quality/billing, повторный импорт без дубликатов и heartbeat worker.
  Smoke отправляет CSV через frontend proxy, включая файл больше 1 MiB.
- Остановка настоящей БД: readiness 503, liveness 200, system info unavailable;
  после возврата БД readiness снова 200.

Локально PostgreSQL 14.24 и Python 3.12; CI использует PostgreSQL 17. Docker daemon в
среде недоступен, поэтому Docker build/Compose и настоящий Prometheus проверяются отдельным
CI job. `compose.collection-test.yaml` включает исключительно синтетический exporter,
настоящий Prometheus и read-only сбор через query/query_range; этот override не используется
обычным запуском. Результат удалённого запуска относится к конкретному commit в GitHub Actions.

## Границы проверки

Kubernetes connector проверен официальным SDK на API-fixtures. Пользовательский кластер,
его credentials, RBAC и настоящие cAdvisor labels не предоставлены; подключение к нему
не подтверждено. Нет заявлений об измерениях или экономии в реальной инфраструктуре.

Браузер среды не видит localhost исполнительной среды. UI проверен компонентными тестами,
TypeScript/build и HTTP proxy/SPA, без заявления о визуальной проверке реального браузера.

Рекомендации, AI, feasibility/capacity planning, k6 lab, autoscaling и применение изменений
не реализованы. Следующий этап не запускается автоматически. Авторизации нет; текущий
Compose публикует приложение только на loopback. Поиск уязвимостей зависимостей в этот
набор проверок не входит; прежнее ограничение dev dependency audit не считается устранённым.

Контракты, форматы, ограничения и запуск — [collection.md](collection.md).
