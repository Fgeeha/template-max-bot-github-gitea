# CLAUDE.md

Правила работы для агента в этом репозитории. Читать перед каждой задачей.

---

## 0. ЗАПРЕТЫ В КОММИТАХ И ИСТОРИИ (жёстко, без исключений)

Эти правила имеют наивысший приоритет. Нарушение = откатить коммит.

- В сообщениях коммитов, в теле PR, в комментариях кода, в `CHANGELOG`, в авторстве
  и в любых артефактах репозитория **ЗАПРЕЩЕНО** упоминать: `Claude`, `Anthropic`,
  `claude.ai`, `claude code`, `AI`, `ИИ`, `сгенерировано`, `assistant`, `LLM`,
  «при помощи нейросети» и любые синонимы, прямо или косвенно указывающие на
  происхождение кода от ИИ-ассистента.
- **НЕ добавлять** трейлеры вида `Co-Authored-By: Claude ...`,
  `Generated with ...`, `🤖 ...` и подобные. Коммиты должны выглядеть как
  написанные человеком-разработчиком.
- **НЕ менять** `user.name` / `user.email` в git-конфиге. Использовать те, что
  уже настроены в окружении. Если они не настроены — остановиться и спросить.
- Сообщения коммитов — на русском, в стиле Conventional Commits
  (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`), по делу, без воды и эмодзи.
- Перед каждым `git commit` мысленно проверить тело и заголовок на наличие
  запрещённых слов. Если хоть одно есть — переписать.

---

## 1. Что это

Шаблон чат-бота для мессенджера [MAX](https://max.ru) на `maxapi`, с CI/CD под
GitHub Actions и Gitea Actions. Подробное описание архитектуры, конфигурации,
решений и их обоснования — в [`README.md`](README.md); не дублировать его
содержимое здесь, только команды и ориентиры для быстрой работы.

## 2. Команды

```bash
make install       # uv sync — базовые зависимости
make install-all    # uv sync --all-extras — с БД и метриками
make run            # запуск бота локально (polling)
make lint           # ruff check src tests
make format          # ruff check --fix + ruff format
make test           # pytest (герметичные тесты, без сети и без .env)
make check           # lint + test + ruff format --check — перед коммитом
```

Один тест: `uv run pytest tests/test_config.py::test_admin_ids_parsing`.

Docker/БД/CI — см. `make help` и разделы README «Команды Makefile», «Docker»,
«CI/CD», «Закрытый контур».

## 3. Архитектура

Точка входа `src/bot/__main__.py` выбирает режим (`polling`/`webhook`) из
`config.py` (единственный источник настроек, `pydantic-settings`, валидация
при старте — не при первом обращении), собирает `Dispatcher` и делает
graceful shutdown по SIGINT/SIGTERM.

`runtime.py` — патчи поверх `maxapi`: два независимых rate-лимита (общий RPS и
более строгий на отправку сообщений), ретраи на 429 (тот приходит как
`ContentTypeError`, не как HTTP-статус), sliding window вместо сбрасываемого
счётчика.

Регистрация в `handlers/__init__.py:register_all` **порядок-зависима**:
outer middleware (`maintenance` → `throttling`) → хендлеры команд/callback'ов
(`admin` → `start` → `menu`) → catch-all свободного текста последним. Новый
хендлер добавлять строго до `menu.register(dp)`.

`keyboards/callbacks.py` — типизированные payload'ы кнопок (единственное
место, где завязаны кнопка и её обработчик); `keyboards/menus.py` — разделы
меню как данные (`SECTIONS`), не код.

`db/` (опционально, требует `DATABASE_URL` и `--extra db`) — SQLAlchemy async
+ Alembic; весь SQL только в `db/repositories/`, хендлеры к сессии напрямую не
обращаются. `alembic.ini` не содержит DSN — берётся из `config.py`.

`webhook.py` — маршрут отвечает MAX сразу, обработка апдейта уходит в фоновую
задачу (`BackgroundDispatcher`), не удерживая HTTP-соединение; очередь
ограничена `WEBHOOK_MAX_PENDING_UPDATES`, размер виден в `/healthz`.

Соглашение по размеру файла — до 400 строк; при превышении делить на модули.
Комментарии и docstring'и — на русском.
