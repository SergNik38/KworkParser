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

4. Запустите одну итерацию:

```bash
python3 -m kwork_parser --once
```

5. Когда результат устроит, включите отправку:

- задайте `TELEGRAM_BOT_TOKEN`
- задайте `TELEGRAM_CHAT_ID`
- переключите `KWORK_DRY_RUN=false`

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
