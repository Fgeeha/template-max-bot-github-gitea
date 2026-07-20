"""Регистрация middleware и хендлеров в диспетчере."""

from maxapi import Dispatcher


def register_all(dp: Dispatcher) -> None:
    """Подключает всё, что обрабатывает события.

    Порядок значим:
      1. outer middleware — до фильтров: сначала гейт доступа, затем лимиты
         (не имеет смысла тратить слот лимита на заблокированного клиента);
      2. хендлеры команд и callback'ов — со своими фильтрами;
      3. catch-all для свободного текста — последним, иначе перехватит всё.
    """
    from bot.handlers import admin, menu, start
    from bot.middlewares.maintenance import MaintenanceMiddleware
    from bot.middlewares.throttling import ThrottlingMiddleware

    dp.register_outer_middleware(MaintenanceMiddleware())
    dp.register_outer_middleware(ThrottlingMiddleware())

    admin.register(dp)
    start.register(dp)
    menu.register(dp)
