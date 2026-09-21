# CI на ml110 — self-hosted runner

Минуты GitHub Actions на приватном репозитории кончаются: 2000 в месяц, к 21.09 ушло 90 %,
а один прогон `quality` стоит 8 минут. Runner на ml110 минут не тратит, а образ
с зависимостями там уже есть.

Workflow (`.github/workflows/ci.yml`) ждёт runner с меткой `self-hosted`. Пока runner
не зарегистрирован, проверки PR стоят в очереди — поэтому PR с новым workflow
сливается **после** шагов ниже.

## Кто что делает

Репозиторий личный (`sMichellin/slide_write_gen_vid`). В личном репозитории у соавтора
одна роль — запись; ни админа, ни отдельного права «только на runner» GitHub соавтору
не даёт (роли admin/maintain и пользовательские роли есть только у репозиториев
организации). Поэтому доступ передаётся **токеном регистрации**: он годится только
на то, чтобы подключить runner, живёт час и ничего больше не открывает.

1. **Владелец (sMichellin)** выпускает токен и передаёт его Freel-Freel личным сообщением:

   ```bash
   gh api -X POST repos/sMichellin/slide_write_gen_vid/actions/runners/registration-token --jq .token
   ```

   Или в вебе: Settings → Actions → Runners → New self-hosted runner → Linux x64 —
   токен в команде `./config.sh`.

2. **Freel-Freel** ставит runner на ml110 под отдельным пользователем `gitlab-runner`
   (шаги ниже).

3. **Владелец** проверяет, что runner `ml110` в Settings → Actions → Runners — Idle,
   и сливает PR с workflow.

Если нужен именно полный доступ Freel-Freel к настройкам Actions — единственный путь
перенести репозиторий в организацию (Settings → Danger Zone → Transfer) и дать ему роль
Admin на репозиторий. Ссылки на старый адрес GitHub перенаправит, но `origin` у всех
лучше обновить.

## Установка runner (Freel-Freel, на ml110)

**Как стоит сейчас (21.09):** runner `ml110` зарегистрирован, распакован в
`/home/gitlab-runner` и работает под отдельным пользователем `gitlab-runner`: `.env`
стенда и файлы `smichellin` ему недоступны. Метки: `self-hosted, Linux, X64, podman`.
Podman — `/usr/bin/podman` (rootless, subuid/subgid у пользователя есть).

**Осталось запустить его как сервис** (нужен sudo):

```bash
# rootless podman без открытой сессии пользователя требует /run/user/<uid>
sudo loginctl enable-linger gitlab-runner
cd /home/gitlab-runner
sudo ./svc.sh install gitlab-runner
sudo ./svc.sh start
sudo ./svc.sh status
```

Проверка: в Settings → Actions → Runners у `ml110` статус **Idle**, и под пользователем
`gitlab-runner` работает podman:

```bash
sudo -iu gitlab-runner podman info --format '{{.Store.GraphRoot}}'
```

Первый job соберёт образ `deckforge-ci` в хранилище `gitlab-runner` (5–10 мин,
нужен доступ в PyPI); дальше образ берётся готовым.

Установка с нуля — на случай переустановки. Токен вводится руками и никуда не пишется:

```bash
V=2.337.0   # актуальная: https://github.com/actions/runner/releases/latest
sudo -iu gitlab-runner
curl -sSLo runner.tgz https://github.com/actions/runner/releases/download/v$V/actions-runner-linux-x64-$V.tar.gz
tar xzf runner.tgz && rm runner.tgz
read -rs TOKEN
./config.sh --unattended --url https://github.com/sMichellin/slide_write_gen_vid \
  --token "$TOKEN" --name ml110 --labels podman --work _work
unset TOKEN
```

## Что делает job на ml110

Замер 21.09 на ml110: весь job — 1 мин 40 с (1163 теста), против 8 мин в облаке.

* собирает образ `localhost/deckforge-ci:<хэш pyproject.toml и Dockerfile>` — только
  когда зависимости поменялись; иначе берёт готовый;
* гоняет ruff, mypy, гейты C1/C2 и C6 и тесты **в контейнере без сети** с одним
  смонтированным чекаутом: `.env` стенда и прочие файлы сервера тесты не видят, к LLM
  не ходят. Сами шаги workflow идут под `gitlab-runner`, у которого нет доступа
  к стенду `smichellin`;
* удаляет прежние теги `deckforge-ci:*` — только свои; `podman image prune -a`
  не используется (на сервере образы других проектов).

## Правила

* Runner принимает job только из этого репозитория, а PR в приватный репозиторий
  открывают только соавторы — чужой код на сервере не выполнится.
* Стенд (`~/deckforge`, `api.sh`, `.env`) runner не трогает: деплой по-прежнему
  руками из `main` (DEPLOY-ml110.md).
* Остановить: `sudo ./svc.sh stop` в `/home/gitlab-runner`. Снять совсем:
  `./config.sh remove --token <токен удаления>` (Settings → Actions → Runners → Remove).
* Вернуть облачный CI — в `ci.yml` заменить `runs-on` на `ubuntu-latest` и вернуть
  шаги poetry из истории файла.
