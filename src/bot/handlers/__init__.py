"""Регистрация middleware и хендлеров в диспетчере."""

from maxapi import Dispatcher


def register_all(dp: Dispatcher) -> None:
    """Подключает всё, что обрабатывает события.

    Порядок значим:
      1. outer middleware — до фильтров: сначала гейт доступа, затем лимиты
         (не имеет смысла тратить слот лимита на заблокированного клиента);
      2. хендлеры команд и callback'ов — со своими фильтрами; админка
         (editor) — до menu, иначе её кнопки и ввод заберёт пользовательская
         навигация;
      3. catch-all для свободного текста и кнопок — последним (menu).
    """
    from bot.handlers import admin, editor, menu, start
    from bot.middlewares.maintenance import MaintenanceMiddleware
    from bot.middlewares.throttling import ThrottlingMiddleware

    dp.register_outer_middleware(MaintenanceMiddleware())
    dp.register_outer_middleware(ThrottlingMiddleware())

    admin.register(dp)
    editor.register(dp)
    start.register(dp)
    menu.register(dp)
