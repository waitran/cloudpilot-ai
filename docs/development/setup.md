# Локальное окружение

## Этап 0

Требуются Git и Python 3.12. Системный Python Ubuntu менять не нужно.
uv уже обнаружил установленный пользовательский Python 3.12.16; `python3` указывает на 3.10.12.
Используйте `python3.12`, не `python3`, либо выберите подходящий интерпретатор в IDE.

```bash
python3.12 --version
make check test
```

Если интерпретатор отсутствует и сеть доступна: `uv python install 3.12`.
В ограниченном окружении кеш uv можно направить в доступную директорию:
`UV_CACHE_DIR=/tmp/cloudpilot-uv-cache uv python list --only-installed`.
Виртуальное окружение и зависимости приложения создаются на этапе 1.

## Инструменты для следующих этапов

- Node.js: `.nvmrc` задаёт 24 LTS. Текущий Node 20.20.2 формально соответствует минимальному
  требованию Vite, но для нового проекта выбран поддерживаемый LTS. Установите через уже
  используемый менеджер Node или официальный архив с проверкой checksum. Глобальный Node не заменять.
- Docker/Compose установлены. `docker info` сейчас возвращает permission denied.
  Для этапа 0 daemon не нужен. Для этапа 1 настройте rootless Docker либо попросите администратора
  выдать доступ; членство в группе docker даёт широкие права. Не используйте `chmod 666` для сокета.
- GitHub CLI отсутствует. Безопасный вариант без sudo — официальный Linux x86_64 архив из
  релиза `cli/cli`, проверка SHA256 по release checksums и распаковка в пользовательский `~/.local`.
  Не запускайте непроверенные установочные скрипты через pipe в shell.
- ripgrep необязателен; в текущем окружении отсутствует.

## Завершение GitHub-публикации

В текущем терминале DNS `api.github.com` не работает, поэтому скачать `gh`, проверить его
авторизацию, создать репозиторий и выполнить push невозможно. Наличие старого конфигурационного
файла `gh` не доказывает действующую авторизацию. Токены в чат передавать не нужно.

После установки `gh` и восстановления сети из корня проекта:

```bash
gh auth status
# Только если авторизации нет:
gh auth login --hostname github.com --git-protocol https --web
```

Далее выполните команды последовательно. Остановитесь при любой ошибке.

```bash
owner=$(gh api user --jq .login)
gh repo view "$owner/cloudpilot-ai" --json nameWithOwner,isPrivate,url
```

Если репозиторий найден — изучите его содержимое и историю, ничего не перезаписывайте.
Продолжать следующий блок можно **только** при подтверждённом отсутствии репозитория
(HTTP 404 при действующей авторизации). Ошибки сети/доступа не означают отсутствие репозитория.

```bash
make check test
git status --short --branch
git remote -v
# Убедитесь, что origin ещё отсутствует; репозиторий с таким именем не существует.
gh repo create "$owner/cloudpilot-ai" --private --source=. --remote=origin
git push -u origin main
gh repo view "$owner/cloudpilot-ai" --json nameWithOwner,isPrivate,url
git ls-remote origin refs/heads/main
git rev-parse HEAD
gh run list --branch main --limit 5
```

Сравните SHA удалённой main и HEAD. Найдите CI run именно этого SHA, затем
`gh run watch RUN_ID --exit-status` и при ошибке `gh run view RUN_ID --log-failed`.
Удалённый этап завершён только после проверки private-видимости, совпадения SHA и результата CI.
Не используйте force push. После публикации обновите текущий статус README и отчёт этапа 0.

## Первичные источники

- [GitHub CLI: установка](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
- [GitHub CLI: авторизация](https://cli.github.com/manual/gh_auth_login)
- [GitHub CLI: создание репозитория](https://cli.github.com/manual/gh_repo_create)
- [uv: установка Python](https://docs.astral.sh/uv/guides/install-python/)
- [Node.js: поддерживаемые релизы](https://nodejs.org/en/about/previous-releases)
- [Vite: требования](https://vite.dev/guide/)
- [actions/checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)
- [actions/setup-python v7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0)
