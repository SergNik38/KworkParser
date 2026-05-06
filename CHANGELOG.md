# Changelog

Все заметные изменения в этом проекте будут описаны в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
и этот проект придерживается [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Первый MVP-релиз проекта
- Парсер Kwork.ru с rule-based фильтрацией
- Интеграция с AI (OpenRouter) для анализа заказов
- Telegram Bot с callback-кнопками
- SQLite хранилище для отслеживания проектов
- Docker & Docker Compose поддержка
- Генерация черновиков откликов

### Features
- ✨ Автоматический опрос новых проектов на Kwork
- 🤖 AI-анализ релевантности заказов
- 💬 Telegram уведомления в реальном времени
- 💾 Persistent storage проектов и feedback
- 🔧 Гибкая конфигурация через .env
- 📊 Статистика и health-check команды
- 🚀 Запуск через Docker или локально

### Known Issues
- Kwork имеет ограничения на автоматизацию — используйте с разумной частотой

## [0.1.0] - 2026-05-06

### Initial Release
- Базовый функционал парсера
- MVP версия для личного использования
