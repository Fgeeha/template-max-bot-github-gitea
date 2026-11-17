"""Заглушки событий MAX и помощники сценарных тестов админки.

Хендлеры вызываются напрямую: нажатие кнопки — press, сообщение — send.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from maxapi.enums.attachment import AttachmentType
from maxapi.enums.chat_type import ChatType

from bot.handlers import editor, menu
from bot.keyboards.callbacks import AdminPayload, SectionPayload

ADMIN = 1
STRANGER = 2


class Replies:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    async def answer(self, **kwargs: Any) -> None:
        self.items.append(kwargs)

    @property
    def last(self) -> dict[str, Any]:
        return self.items[-1]


class FakeMessage:
    def __init__(
        self,
        user_id: int,
        text: str,
        replies: Replies,
        chat_type: ChatType = ChatType.DIALOG,
        image_token: str | None = None,
    ) -> None:
        self._user_id = user_id
        attachments = (
            [SimpleNamespace(type=AttachmentType.IMAGE, payload=SimpleNamespace(token=image_token))]
            if image_token
            else []
        )
        self.message = SimpleNamespace(
            body=SimpleNamespace(text=text, attachments=attachments),
            recipient=SimpleNamespace(chat_type=chat_type),
            answer=replies.answer,
        )

    def get_ids(self) -> tuple[int, int]:
        return 100, self._user_id


class FakeCallback:
    def __init__(self, user_id: int, payload: str, replies: Replies, edits: Replies) -> None:
        self._user_id = user_id
        self.callback = SimpleNamespace(payload=payload)
        self.message = SimpleNamespace(answer=replies.answer)
        self.answer = edits.answer

    def get_ids(self) -> tuple[int, int]:
        return 100, self._user_id


def buttons(reply: dict[str, Any]) -> dict[str, str]:
    """Подпись → payload (у кнопки-ссылки — url) по всем кнопкам сообщения."""
    return {
        button.text: getattr(button, "payload", None) or button.url
        for markup in reply.get("attachments") or []
        if hasattr(markup.payload, "buttons")
        for row in markup.payload.buttons
        for button in row
    }


async def press(user_id: int, payload: str) -> tuple[Replies, Replies]:
    replies, edits = Replies(), Replies()
    event_obj = FakeCallback(user_id, payload, replies, edits)
    if AdminPayload.matches(payload):
        await editor.on_admin_callback(event_obj)
    else:
        await menu.on_callback(event_obj)
    return replies, edits


async def navigate(user_id: int, payload: str) -> dict[str, Any]:
    """Нажатие в пользовательском меню: экран меняется в том же сообщении."""
    replies, edits = await press(user_id, payload)
    assert replies.items == [], "навигация не должна слать новые сообщения"
    return {**edits.last, "text": edits.last["new_text"]}


async def send(user_id: int, text: str, image_token: str | None = None) -> Replies:
    replies = Replies()
    event_obj = FakeMessage(user_id, text, replies, image_token=image_token)
    if await editor.PendingInput()(event_obj):
        await editor.on_admin_input(event_obj)
    else:
        await menu.on_free_text(event_obj)
    return replies


class FailingEdit:
    """Заглушка правки сообщения, которая падает с заданной ошибкой."""

    def __init__(self, exc: Exception, message: bool = True) -> None:
        self.replies, self.acks, self.sent = Replies(), Replies(), Replies()
        self.event = FakeCallback(
            STRANGER, SectionPayload(section_id=999).pack(), self.replies, Replies()
        )
        self.event.callback.user = SimpleNamespace(user_id=STRANGER)
        self.event.ack = self.acks.answer
        self.event.bot = SimpleNamespace(send_message=self.sent.answer)
        if not message:
            self.event.message = None

        async def _raise(**_kwargs: Any) -> None:
            raise exc

        self.event.answer = _raise
