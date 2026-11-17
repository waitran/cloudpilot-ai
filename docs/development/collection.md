# Сбор данных: запуск и контракты

Этап 2 добавляет read-only discovery, метрики, импорт биллинга и проверку качества.
Нет рекомендаций, LLM, изменения requests/limits, масштабирования или обещаний экономии.

## Запуск

```bash
python3.12 scripts/init_env.py
docker compose up --build --wait --wait-timeout 180
```

Открыть `/sources` во frontend: зарегистрировать источник, выбрать scope и тип данных,
затем отправить CSV либо запустить sync. `/resources` показывает реальные записи из БД.
Новый запуск не создаёт источники или демоданные автоматически.

Worker — отдельный сервис Compose. Для нативной разработки после `alembic upgrade head`:

```bash
cd backend
uv run python -m cloudpilot.modules.collection.tasks.worker
```

Проверка worker: `docker compose exec -T worker python -m cloudpilot.modules.collection.tasks.worker --check`.
Heartbeat хранится в PostgreSQL; API показывает `collector=unavailable`, если нет heartbeat
за 5 минут. API readiness проверяет БД и остаётся работоспособным при недоступном connector.

API предназначен для локальной разработки без авторизации. Порты Compose привязаны к
127.0.0.1. Перед внешней публикацией нужны аутентификация, контроль доступа и TLS.

## Источники и идентичность

`POST /api/v1/sources` принимает только `name`, `type` (`csv`, `kubernetes`, `prometheus`),
`scope`, `is_synthetic`. URL, PromQL, токены и пути не принимаются по HTTP.
Настройки соединения задаются оператором через окружение сервера.

Scope — идентификатор аккаунта или кластера. Источники inventory, metrics и billing
должны иметь одинаковые scope и is_synthetic, чтобы данные могли сопоставляться.
Для каждого другого endpoint/кластера нужен отдельный экземпляр worker с соответствующей
БД: в MVP предусмотрен один серверный профиль подключения каждого типа на установку.
Нельзя регистрировать разные реальные кластеры с одним scope.

Идентичность ресурса: `(provider, account_or_cluster_id, external_id, is_synthetic)`.
Для Kubernetes external_id — metadata.uid, включая pods; новое воплощение pod с прежним
именем остаётся отдельным ресурсом. Последний inventory-источник записывается в source_id;
metric/billing сохраняют собственный source_id. История ресурса не удаляется при discovery.

Prometheus-профиль cAdvisor собирает CPU cores и memory working-set bytes для pods.
При наличии uid/pod_uid используется UID. Без UID требуется уникальный pod в свежем
Kubernetes inventory той же области, namespace/name и время внутри подтверждённого
жизненного цикла. CSV не может подделать это доказательство через configuration.
Несопоставленная метрика отклоняется, несопоставленный биллинг сохраняется с resource_id=null.
После появления уникального ресурса биллинг связывается повторно. Неоднозначность не
разрешается предположением. CSV ресурсов допускает VM; Prometheus node_exporter/OpenCost
и прямой cloud billing API в этот этап не входят.

## Prometheus

В `.env` задать PROMETHEUS_URL и при необходимости PROMETHEUS_TOKEN. Не помещать
токен в URL. HTTP допустим для доверенной локальной сети; для внешних endpoint нужен HTTPS.
Редиректы и чтение proxy-настроек окружения выключены; сертификат HTTPS проверяется.

Для необязательного локального Prometheus:

```bash
docker compose --profile monitoring up --build --wait
```

`PROMETHEUS_URL=http://prometheus:9090` задаётся отдельно в `.env` для worker. Порт UI
по умолчанию 19090, retention Prometheus 14 дней. Конфигурация в
`infrastructure/monitoring/prometheus.yml` собирает только собственные служебные метрики.
Для CPU/RAM требуется явно подключить свой разрешённый cAdvisor target. Самосбор
Prometheus не является показателем потребления CPU/RAM ресурсов.

Используются `/api/v1/query` (доступность API) и `/api/v1/query_range`. Фиксированные
запросы профиля `cadvisor-pods-v1` находятся в connector; произвольный PromQL отсутствует.
Окно до 7 дней, step 15–3600 секунд, до 10 000 точек в серии, 100 серий и 50 000 точек
на метрику; ответ ограничен 4 MiB. Таймаут чтения 20 секунд, подключения 3 секунды.
HTTP-ошибка, предупреждение partial response и неверный формат фиксируются кодом ошибки.
NaN/Inf, отрицательные значения и неполные серии не становятся нулями. CPU хранится с
точностью 9 знаков, память — целые bytes. Отсутствующая метрика оставляет partial run.

## Kubernetes

Официальный Python client 35.x; целевая совместимость — Kubernetes 1.35. На другой версии
нужно отдельно проверить совместимость API. Поддерживаются два явных режима:

- `KUBE_MODE=kubeconfig`, `KUBE_CONFIG_FILE=/chosen/path/config`, необязательный KUBE_CONTEXT.
- `KUBE_MODE=incluster`, service account контейнера worker.

По умолчанию `KUBE_MODE=disabled`. Домашний kubeconfig не читается и не монтируется
автоматически. В Compose путь нужно явно смонтировать read-only через локальный override;
конфигурация и сертификаты должны быть доступны UID 10001. Использовать только доверенный
kubeconfig: exec authentication может запускать указанный в нём credential plugin.
TLS verification не разрешено выключать. Секреты, env контейнеров и annotations не собираются.

Шаблон RBAC: `infrastructure/kubernetes/collection-rbac.yaml`. Он не применяется автоматически.
Разрешены только get/list nodes, namespaces, pods, deployments, statefulsets. Connector
не вызывает create/update/patch/delete/scale. Namespace names хранятся в metadata источника.
Inventory ограничен 5000 объектами каждого вида и 10 страницами по 500; общий deadline
180 секунд проверяется между запросами, каждый запрос имеет timeout (3, 15).

Requests, limits, capacity, allocatable хранятся раздельно. 100m = 0.1 cores,
128Mi = 134217728 bytes. Pod requests учитывают обычные и init-контейнеры,
restartable init sidecars, pod-level resources и overhead. Отсутствующий конечный limit
не превращается в 0. Для Deployment/StatefulSet requests/limits относятся к одной реплике
и помечены `request_scope=per_replica`; replicas записывается отдельно. Факт usage
не выводится из requests. Исчезнувший из полного inventory объект получает not_seen;
история и UID сохраняются.

## CSV

`POST /api/v1/imports/csv`: multipart `source_id`, `kind`, `file`. Источник должен быть csv.
Файл UTF-8/UTF-8 BOM, до 2 MiB и 10 000 строк. HTTP-body ограничен до парсинга multipart.
Никаких локальных путей или загрузки по URL. Неправильные headers/кодировка/структура файла
отклоняют запрос; невалидные строки фиксируются в IngestionRun с номером строки.

| kind | Обязательные колонки | Дополнительные поля |
| --- | --- | --- |
| resources | external_id, resource_type, name | provider, namespace, region, availability_zone, status, cpu_capacity, memory_capacity_bytes, cpu_requests, memory_requests_bytes, cpu_limits, memory_limits_bytes, cpu_allocatable, memory_allocatable_bytes, labels |
| metrics | external_resource_id, metric_name, value, unit, timestamp | expected_interval_seconds (по умолчанию 60) |
| billing | external_resource_id, service, period_start, period_end, amount, currency | external_record_id, cost_type (по умолчанию actual) |

Типы ресурсов: virtual_machine, kubernetes_node, kubernetes_pod,
kubernetes_deployment, kubernetes_statefulset. Provider по умолчанию csv для VM и
kubernetes для Kubernetes типов. CPU конфигурации — cores, memory — целые bytes.
Labels — JSON object; потенциально секретные ключи не принимаются. Непустое configuration
из CSV запрещено, чтобы импорт не подделал lifecycle metadata.

Метрики: cpu_usage_cores (cores или millicores), memory_usage_bytes (bytes, KiB, MiB, GiB),
network_receive_bytes_per_second и network_transmit_bytes_per_second (bytes/s),
cpu_throttling_ratio (ratio 0..1). Последние три доступны через CSV, текущий Prometheus
профиль их не собирает. Отрицательные/NaN/Inf и неподходящие единицы отклоняются.

Времена обязаны иметь timezone и приводятся к UTC. Для clock skew допускаются 2 минуты
вперёд; более поздние metric timestamps отклоняются. Billing period_end > period_start;
будущее разрешено только для forecast. Поддерживаемые валюты перечислены в BillingInput
(USD, EUR, RUB и другие); неизвестный код отклоняется. Валюты не конвертируются.
Деньги — Decimal/Numeric(24,9), в JSON строка, без float-арифметики. Cost types:
actual, estimated, forecast, credit. Отрицательная сумма разрешена только для credit.
Периодный фильтр выбирает пересекающиеся записи целиком, без пропорционального пересчёта.

Дедупликация: resources по стабильной идентичности; metrics по resource/source/name/time;
billing по source/external_record_id. При отсутствии billing ID вычисляется SHA-256
нормализованной строки. Для корректировок нужно передавать прежний внешний ID; изменённая
строка без внешнего ID считается новой записью. Дубликат внутри файла отклоняет строку,
повторная загрузка файла обновляет существующие записи. Конфликтующие метрики разных
источников не усредняются; качество помечается multiple_metric_sources.

Шаблоны: `tests/fixtures/collection/{resources,metrics,billing}.csv` — явно **синтетические**.
Для них создать источник с `is_synthetic=true`, scope например `demo`, загрузить resources,
metrics, billing по очереди. Время fixture фиксированное: данные вне 8-дневного окна оцениваются как unavailable
и insufficient_history, это не показания работающей инфраструктуры. Никакой файл не импортируется при старте.

## Очередь и качество

HTTP сохраняет job/payload в PostgreSQL, возвращает 202 и IngestionRun.id. Worker берёт
задание через FOR UPDATE SKIP LOCKED, коммитит lease, затем собирает данные вне транзакции.
Lease 10 минут, максимум 3 попытки после потери процесса. Финальный commit проверяет owner,
так что старый worker не может записать результат после повторного захвата lease.
Один pending/running job на источник обеспечен partial unique index, конфликт возвращает 409.
Результат загрузки и финальное состояние job фиксируются одной транзакцией; savepoint
изолирует невалидные строки. После terminal status payload очищается, отчёт остаётся.
Потеря БД откатывает транзакцию и оставляет job для восстановления после истечения lease.

Статусы run: pending/running/completed/partial/failed; read/created/updated/rejected,
created/started/finished, attempts и до 100 безопасных ошибок с кодами. Последний полностью
успешный сбор хранится отдельно и не сбрасывается ошибкой. Обрыв connector не удаляет
хорошую историю и не останавливает другие источники. Raw exception и credentials не
попадают в API или отчёт. Автоматическое расписание sync в MVP отсутствует.

Качество ресурса: healthy/partial/stale/unavailable/invalid. Проверяется доступность CPU и RAM,
7 дней истории по каждой метрике, gap > 1.5 ожидаемого интервала, свежесть 15 минут,
свежесть inventory 24 часа, деградация источника, конфликт источников и превышение
известной capacity. Окно оценки — последние 8 дней. Агрегация и обнаружение gaps выполняются
SQL-запросом; серия одного источника не закрывает пропуски другого. Отсутствие метрик
показывается как unavailable. `/data-quality/summary` ограничен 1000 ресурсами; превышение
явно возвращает ошибку вместо неполной сводки. Для больших парков нужны фоновые snapshots.

`optimization_ready` означает прохождение этих проверок данных, а не безопасность изменения
ресурсов или достижимость SLO. Это не оценка производительности будущей конфигурации.
Синтетические записи всегда видимо помечены и отделены при связывании и суммировании.
Расчёта savings, прав на изменение инфраструктуры и автоматического применения нет.
Хранимую историю этот этап автоматически не удаляет; retention PostgreSQL — отдельная
эксплуатационная политика, которую нужно выбрать перед длительным сбором.

## Query API

| Endpoint | Назначение |
| --- | --- |
| GET/POST /api/v1/sources | Реестр / регистрация источника |
| GET /api/v1/sources/{id} | Статус, last_success/error и discovery metadata |
| POST /api/v1/sources/{id}/sync | Job с start/end/step для server-owned connector |
| POST /api/v1/imports/csv | Загрузка проверяемых строк в durable queue |
| GET /api/v1/ingestion-runs[/{id}] | История и отчёт job, без payload и секретов |
| GET /api/v1/resources[/{id}] | Inventory, конфигурация, latest metrics, качество |
| GET /api/v1/resources/{id}/metrics | Временные ряды с start/end (до 7 дней), metric_name |
| GET /api/v1/resources/{id}/billing | Связанные записи, фильтр пересечения периода |
| GET /api/v1/billing/summary | Decimal суммы по currency/cost_type/is_synthetic |
| GET /api/v1/data-quality/summary | Числа ресурсов по состояниям и пригодности данных |

Коллекции: `items,total,limit,offset`, limit 1–200, offset до 100000. Resources поддерживает
q (literal substring), source_id, resource_type, namespace, is_synthetic и allowlist sort
(name/last_seen). Billing summary поддерживает source_id, is_synthetic, start/end (до 366 дней).
Полные Pydantic контракты и ошибки — `/docs`, `/openapi.json`. Даты без timezone не принимаются.
UI показывает страницы по 20 ресурсов, до 200 samples на странице графика и последние 20 jobs.
График рисует отдельные наблюдения, без интерполяции. Реестр UI показывает первые 200 источников;
для более длинной истории/реестра используется пагинированный API.

## Проверки

```bash
uv run --project backend pytest backend/tests -q
cd frontend && npm test && npm run build
```

Для интеграционных тестов обязателен TEST_DATABASE_URL на отдельную БД с суффиксом `_test`.
Без TEST_DATABASE_URL эти проверки явно пропускаются. Тесты проверяют миграции, очередь, повторы, reconciliation, scope/synthetic isolation,
ошибки API, границы входа, SQL-оценку качества, SDK read-only запросы и NaN/ошибки Prometheus.

`make smoke` явно создаёт synthetic source, загружает три CSV, проверяет worker/БД и повторы.
В CI дополнительно запускается настоящий Prometheus с отдельным synthetic exporter:

```bash
docker compose -f compose.yaml -f compose.collection-test.yaml --profile monitoring up --build --wait
python3 scripts/smoke_collection.py
python3 scripts/smoke_prometheus.py
docker compose -f compose.yaml -f compose.collection-test.yaml --profile monitoring down
```

Этот override не включается обычным запуском. Exporter — тестовый процесс, а не клиентская
инфраструктура. Kubernetes SDK проверяется на API-fixtures; реальный кластер пользователя
не был предоставлен, его доступность и RBAC нужно проверить отдельно после подключения.

Основные первичные документы:
[Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/),
[официальный Kubernetes Python client](https://github.com/kubernetes-client/python),
[Resource Management for Pods](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/),
[RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/).
