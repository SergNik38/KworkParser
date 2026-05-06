# Contributing to Kwork Parser

Спасибо за интерес к проекту! Любые улучшения приветствуются.

## Быстрый старт для разработки

```bash
git clone https://github.com/SergNik38/KworkParser.git
cd KworkParser
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Запуск тестов

```bash
python3 -m unittest discover tests -v
```

Все тесты должны проходить перед отправкой PR. CI автоматически проверяет Python 3.10, 3.11, 3.12.

## Как отправить PR

1. Форкните репозиторий и создайте ветку: `git checkout -b feature/my-feature`
2. Внесите изменения, убедитесь что тесты проходят
3. Добавьте тест, если добавляете новую логику
4. Откройте Pull Request с описанием что и зачем изменили

## Структура проекта

```
kwork_parser/
├── app.py              # Оркестрация цикла опроса
├── kwork.py            # HTTP-клиент Kwork API
├── scoring.py          # Rule-based и AI scoring
├── notifier.py         # Telegram Bot API
├── storage.py          # SQLite хранилище
├── response_drafts.py  # Генерация черновиков откликов
├── config.py           # Конфигурация через .env
└── models.py           # Dataclass-модели
tests/                  # unittest-тесты
```

## Что нужно проекту

- Поддержка других фриланс-бирж (FL.ru, Freelance.ru)
- Веб-интерфейс для просмотра статистики
- Экспорт избранных заказов в CSV/Notion
- Улучшение AI-промптов

Открытые задачи — в [Issues](https://github.com/SergNik38/KworkParser/issues).
