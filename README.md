# Kwork Parser MVP

MVP-сервис, который:

- опрашивает биржу проектов Kwork через `POST https://kwork.ru/projects`
- сохраняет уже увиденные проекты в `SQLite`
- отсеивает шум через rule-based фильтр
- при желании догоняет кандидатов через OpenRouter
- отправляет новые интересные проекты в Telegram

Важно: у Kwork есть ограничения на автоматизацию, поэтому используйте проект аккуратно, с разумной частотой запросов и на свой риск.

## Быстрый старт

1. Создайте виртуальное окружение и установите зависимости:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Подготовьте конфиг:

```bash
cp .env.example .env
```

3. Для первого запуска оставьте `KWORK_DRY_RUN=true`, чтобы посмотреть кандидатов без отправки в Telegram.
   В dry-run проекты помечаются как просмотренные, но не как отправленные: после переключения
   `KWORK_DRY_RUN=false` подходящие просмотренные проекты останутся доступны для реальной отправки.

4. Запустите одну итерацию:

```bash
python3 -m kwork_parser --once
```

5. Когда результат устроит, включите отправку:

- задайте `TELEGRAM_BOT_TOKEN`
- задайте `TELEGRAM_CHAT_ID`
- переключите `KWORK_DRY_RUN=false`

В реальном Telegram-режиме сообщения содержат inline-кнопки обратной связи:
`Интересно`, `Мимо`, `Скрыть похожие` и `Открыть заказ`.

## Запуск через Docker

Сборка образа:

```bash
docker compose build
```

Первый bootstrap-запуск без фона:

```bash
docker compose run --rm kwork-parser --once
```

Постоянный запуск в фоне:

```bash
docker compose up -d
```

Просмотр логов:

```bash
docker compose logs -f
```

Логи пишутся через стандартный `logging` с уровнем `INFO` по умолчанию. Ошибки AI-анализа,
Telegram-отправки и фонового цикла попадают в лог с traceback, чтобы их можно было разбирать
через `docker compose logs -f` или cron/systemd-журналы.

Остановка:

```bash
docker compose down
```

Важно:

- `.env` не копируется в образ и читается контейнером через `env_file`
- база хранится в локальной папке `data/`, потому что она примонтирована в контейнер
- если нужно разово проверить текущую конфигурацию без фонового процесса, используйте `docker compose run --rm kwork-parser --once`

## Что настраивается

- `KWORK_MAX_PAGES`: сколько первых страниц биржи опрашивать за один цикл
- `KWORK_REQUEST_RETRIES`: сколько раз повторять запрос к Kwork при сетевом сбое
- `KWORK_RETRY_BACKOFF_SECONDS`: пауза между повторами
- `KWORK_SKIP_EXISTING_ON_FIRST_RUN`: при первом запуске только сохранить текущую ленту без уведомлений
- `KWORK_INCLUDE_KEYWORDS`: ключевые слова, которые повышают score
- `KWORK_EXCLUDE_KEYWORDS`: стоп-слова
- `KWORK_CATEGORY_IDS`: whitelist рубрик Kwork
- `KWORK_MIN_PRICE`: минимальный бюджет заказа
- `KWORK_MIN_RULE_SCORE`: порог rule-based фильтра
- `KWORK_MIN_AI_SCORE`: порог AI-анализа через OpenRouter

## OpenRouter

AI-анализ включается автоматически, если заданы:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`

По умолчанию пример использует `openai/gpt-5.2-chat`, но модель лучше выбирать под ваш бюджет и стиль оценки.

Системный промпт AI-фильтра вынесен в отдельный файл:

- `kwork_parser/prompts/development_filter_system_prompt.txt`

Если захотите изменить правила релевантности, удобнее редактировать именно его.

## Telegram feedback

Callback-нажатия с inline-кнопок читаются через Telegram `getUpdates` во время очередного
цикла опроса. Последний обработанный `update_id` хранится в SQLite, поэтому одно и то же
нажатие не обрабатывается повторно.

Обратная связь сохраняется в таблицу `project_feedback`:

- `interesting`: проект интересен
- `miss`: проект не подходит
- `hide_similar`: скрывать похожие проекты в будущих правилах

В групповых чатах обратная связь хранится отдельно для каждого участника по ключу
`project_id + telegram_user_id`. Повторное нажатие того же участника обновляет только
его оценку по этому заказу.

`hide_similar` влияет на следующие циклы опроса: если новый заказ похож на ранее скрытый
по рубрике и значимым словам из заголовка/описания, rule score снижается на 25 пунктов
и в причинах появляется отметка о похожести на скрытый заказ.

## Продакшен-запуск

Для постоянной работы можно:

- запускать процесс в `tmux`/`screen`
- оформить как `systemd` service
- или вызывать `python3 -m kwork_parser --once` по `cron`

## Структура

- `kwork_parser/kwork.py`: клиент Kwork
- `kwork_parser/storage.py`: SQLite-хранилище
- `kwork_parser/scoring.py`: rule-based и AI scoring
- `kwork_parser/notifier.py`: Telegram Bot API
- `kwork_parser/app.py`: orchestration

## Состояния проектов

В SQLite для проектов ведется статус обработки:

- `pending`: проект найден и ждет проверки/отправки
- `previewed`: проект показан в dry-run, но еще не отправлен в Telegram
- `sent`: проект успешно отправлен в Telegram
- `skipped`: проект явно пропущен, например из-за bootstrap или низкого score
- `error`: AI-анализ или Telegram-отправка завершились ошибкой; проект останется в очереди для повтора
