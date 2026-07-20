"""Middleware диспетчера.

Outer middleware вызываются ДО фильтров хендлеров и получают любое событие —
сообщение, callback, системное. Это единственное место, где можно отсечь
обработку целиком (доступ, лимиты, статистика).
"""

from bot.middlewares.maintenance import MaintenanceMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware

__all__ = [
    "MaintenanceMiddleware",
    "ThrottlingMiddleware",
]
