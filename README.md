# Kwork Parser MVP

> **Умный парсер Kwork с AI-анализом и Telegram-уведомлениями**

[![CI](https://github.com/SergNik38/KworkParser/actions/workflows/ci.yml/badge.svg)](https://github.com/SergNik38/KworkParser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)](Dockerfile)
[![GitHub stars](https://img.shields.io/github/stars/SergNik38/KworkParser?style=social)](https://github.com/SergNik38/KworkParser/stargazers)

## 📋 Что это?

**Kwork Parser** — это автоматизированный сервис для поиска релевантных заказов на фрилансе-бирже Kwork.ru. Сервис:

- 🕷️ **Парсит** новые проекты с Kwork через API
- 🧠 **Фильтрует** заказы по rule-based правилам и AI-анализу
- 💬 **Отправляет** уведомления в Telegram в реальном времени
- 💾 **Сохраняет** историю в SQLite для анализа трендов
- 🤖 **Генерирует** черновики откликов через OpenRouter (опционально)
- 📊 **Отслеживает** обратную связь через Telegram-кнопки

**Идеально для:** фрилансеров, которые хотят получать только релевантные заказы вместо спама в ленте.

### ⚠️ Важно
У Kwork есть ограничения на автоматизацию. Используйте проект с разумной частотой опроса (рекомендуется 45-60 сек между запросами).

---

## 🚀 Быстрый старт

### Вариант 1: Docker (рекомендуется)

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/SergNik38/KworkParser.git
cd KworkParser

# 2. Подготовьте конфиг
cp .env.example .env
# Отредактируйте .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID и др.)

# 3. Постройте образ
docker compose build

# 4. Тестовый запуск (dry-run)
docker compose run --rm kwork-parser --once

# 5. Запустите в фоне
docker compose up -d

# 6. Смотрите логи
docker compose logs -f
```

### Вариант 2: Локально

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/SergNik38/KworkParser.git
cd KworkParser

# 2. Создайте виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate  # На Windows: .venv\Scripts\activate

# 3. Установите зависимости
pip install -r requirements.txt

# 4. Подготовьте конфиг
cp .env.example .env
# Отредактируйте .env

# 5. Запустите тест
python3 -m kwork_parser --once

# 6. Запустите в фоне (tmux/screen) или добавьте в cron
python3 -m kwork_parser
```

---

## ⚙️ Конфигурация

### Основные параметры

```env
# Опрос Kwork
KWORK_POLL_INTERVAL_SECONDS=45          # Интервал между запросами (секунды)
KWORK_MAX_PAGES=2                       # Скольких страниц результатов смотреть
KWORK_REQUEST_RETRIES=3                 # Попыток при сетевом сбое
KWORK_DRY_RUN=true                      # true = тест без отправки, false = реально

# Фильтры
KWORK_MIN_PRICE=500                     # Минимальный бюджет
KWORK_MAX_PRICE=100000                  # Максимальный бюджет
KWORK_CATEGORY_IDS=21,22,23             # ID рубрик (оставить пусто = все)
KWORK_INCLUDE_KEYWORDS=python,api,бот   # Ключевые слова для повышения score
KWORK_EXCLUDE_KEYWORDS=wordpress,озвучка # Стоп-слова

# Пороги фильтрации
KWORK_MIN_RULE_SCORE=55                 # Минимальный rule-based score (0-100)
KWORK_MIN_AI_SCORE=70                   # Минимальный AI score (0-100, если включен)

# База данных
KWORK_DATABASE_PATH=data/kwork_parser.db
KWORK_SKIP_EXISTING_ON_FIRST_RUN=true   # На первом запуске пропустить старые заказы
```

### Telegram

```env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11          # Токен от @BotFather
TELEGRAM_CHAT_ID=-1001234567890                                       # ID вашего чата/канала
```

### AI-анализ через OpenRouter

```env
OPENROUTER_API_KEY=sk-or-...            # API ключ OpenRouter
OPENROUTER_MODEL=openai/gpt-4o-mini     # Модель (рекомендуется mini для бюджета)

# Опционально: отдельная модель для генерации откликов
RESPONSE_DRAFT_API_KEY=sk-or-...        # Если не заполнено, используется OPENROUTER_API_KEY
RESPONSE_DRAFT_MODEL=openai/gpt-4       # Модель для откликов

# Ваш профиль для AI (в системном промпте)
AI_PROFILE_BRIEF=Разработчик Python backend, ищу заказы на 5000+
AI_EXTRA_INSTRUCTIONS=Предпочитаю долгосрочные проекты, remote-работу
```

---

## 🔧 Использование

### Первый запуск

1. **Установите `KWORK_DRY_RUN=true`** в `.env`
2. **Запустите** `docker compose run --rm kwork-parser --once` или `python3 -m kwork_parser --once`
3. **Посмотрите результаты** в консоли — проекты будут помечены как "previewed"
4. **Когда убедитесь**, что фильтры работают правильно:
   - Установите `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`
   - Переключите `KWORK_DRY_RUN=false`
   - Запустите снова — подходящие проекты уйдут в Telegram

### Команды

```bash
# Один цикл опроса (тестирование)
python3 -m kwork_parser --once

# Фоновый режим (постоянный опрос)
python3 -m kwork_parser

# Через Docker
docker compose run --rm kwork-parser --once
docker compose up -d  # В фоне
```

### Telegram-команды

- **`/health`** — состояние процесса (доступность, количество проектов, счетчики)
- **Inline-кнопки на каждом проекте:**
  - ✅ **Интересно** — добавить в избранное
  - ❌ **Мимо** — отклонить
  - 👁️ **Скрыть похожие** — не показывать похожие в будущем
  - 🔗 **Открыть заказ** — ссылка на Kwork
  - ✏️ **Отклик** (если AI включен) — сгенерировать черновик отклика

---

## 📊 Архитектура

```
kwork_parser/
├── kwork.py              # Клиент Kwork API
├── storage.py            # SQLite хранилище (проекты, feedback, статусы)
├── scoring.py            # Rule-based и AI scoring
├── response_drafts.py     # Генерация черновиков откликов
├── notifier.py           # Telegram Bot API
├── app.py                # Главная орхестрация
└── prompts/
    └── development_filter_system_prompt.txt  # Системный промпт AI

data/
├── kwork_parser.db       # SQLite база
└── demo_projects/        # Сгенерированные демо-проекты (если AI включен)
```

### Состояния проектов в БД

- `pending` — найден, ждет проверки
- `previewed` — показан в dry-run, готов к отправке
- `sent` — успешно отправлен в Telegram
- `skipped` — пропущен (bootstrap, низкий score)
- `error` — ошибка при обработке (будет повтор)

---

## 🤖 AI-анализ

Если заданы `OPENROUTER_API_KEY` и `OPENROUTER_MODEL`:

1. **Фильтрация** — AI переоценивает каждый проект дополнительно
2. **Генерация откликов** — кнопка "Отклик" создает черновик ответа
3. **Демо-проекты** — если заказ подходит для портфолио, AI может сгенерировать мини-проект

Системный промпт находится в `kwork_parser/prompts/development_filter_system_prompt.txt` — можете его отредактировать под свои критерии.

---

## 🐳 Docker Compose

```bash
# Сборка
docker compose build

# Запуск в фоне с логами
docker compose up -d
docker compose logs -f

# Остановка
docker compose down

# Один запуск
docker compose run --rm kwork-parser --once
```

**Важно:**
- `.env` **не копируется в образ**, читается через `env_file`
- База `data/` **примонтирована** как volume
- Логи выводятся в stdout (видны через `docker compose logs`)

---

## 📝 Примеры конфигурации

### Для Python-разработчика
```env
KWORK_INCLUDE_KEYWORDS=python,django,fastapi,api,парсер,бот,интеграция
KWORK_EXCLUDE_KEYWORDS=wordpress,design,frontend,верстка
KWORK_MIN_PRICE=2000
KWORK_CATEGORY_IDS=21,22,23  # Программирование
KWORK_MIN_RULE_SCORE=60
```

### Для фулстека
```env
KWORK_INCLUDE_KEYWORDS=react,vue,nodejs,typescript,api,fullstack,web
KWORK_EXCLUDE_KEYWORDS=wordpress,design,озвучка
KWORK_MIN_PRICE=3000
KWORK_MIN_RULE_SCORE=50
```

### Для экономии (без AI)
```env
OPENROUTER_API_KEY=  # Оставить пусто
KWORK_MIN_RULE_SCORE=70  # Более строгий фильтр
KWORK_POLL_INTERVAL_SECONDS=120  # Реже проверять
```

---

## 🚀 Продакшен-запуск

### Через cron (каждые 5 минут)
```bash
*/5 * * * * cd /home/user/KworkParser && /usr/bin/python3 -m kwork_parser --once >> /var/log/kwork.log 2>&1
```

### Через systemd service

Создайте `/etc/systemd/system/kwork-parser.service`:
```ini
[Unit]
Description=Kwork Parser Service
After=network.target

[Service]
Type=simple
User=parser
WorkingDirectory=/home/parser/KworkParser
ExecStart=/usr/bin/python3 -m kwork_parser
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Затем:
```bash
sudo systemctl daemon-reload
sudo systemctl enable kwork-parser
sudo systemctl start kwork-parser
sudo journalctl -u kwork-parser -f  # Логи
```

### Через tmux
```bash
tmux new-session -d -s kwork "cd /home/user/KworkParser && python3 -m kwork_parser"
tmux attach -t kwork
```

---

## 🐛 Troubleshooting

### Нет уведомлений в Telegram
- ✅ Проверьте `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`
- ✅ Убедитесь, что `KWORK_DRY_RUN=false`
- ✅ Посмотрите логи: `docker compose logs -f`
- ✅ Тестовый запуск: `docker compose run --rm kwork-parser --once`

### Слишком много спама / мало релевантных
- **Слишком много:** увеличьте `KWORK_MIN_RULE_SCORE` (например, 70-80)
- **Слишком мало:** уменьшите порог (50-60) или добавьте включающие ключевые слова
- **Используйте Telegram-кнопки:** "Интересно" / "Мимо" / "Скрыть похожие" — AI будет учиться

### Ошибки подключения к Kwork
- Проверьте: `KWORK_REQUEST_RETRIES`, `KWORK_RETRY_BACKOFF_SECONDS`, `KWORK_POLL_INTERVAL_SECONDS`
- Увеличьте интервал между запросами (Kwork может ограничивать)
- Смотрите логи для деталей

### AI-анализ не работает
- Проверьте `OPENROUTER_API_KEY` (должен быть действительный)
- Убедитесь в наличии баланса на OpenRouter
- Проверьте `OPENROUTER_MODEL` (используйте mini-версии для экономии)

---

## 🤝 Contributing

Баги, идеи и PR приветствуются! Смотрите [CONTRIBUTING.md](CONTRIBUTING.md) для деталей.

---

## 📄 Лицензия

[MIT License](LICENSE) — используйте свободно, указывайте автора в масштабных проектах.

---

## 👤 Автор

**Sergey Nikishin** ([@SergNik38](https://github.com/SergNik38))

---

## ⭐ Если проект полезен

Пожалуйста, поставьте звезду ⭐ — это помогает другим найти проект!

---

## 🔗 Полезные ссылки

- [Kwork.ru](https://kwork.ru)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [OpenRouter](https://openrouter.ai/)
- [Docker](https://www.docker.com/)

---

**Версия:** 0.1.0-MVP | **Последнее обновление:** 2026-05-06
