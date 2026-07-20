#!/usr/bin/env python3
"""Инициализация нового проекта из шаблона.

Спрашивает имя бота и описание, подставляет их во все файлы, где зашито имя
шаблона, и предлагает начать историю git с нуля.

Запуск: make init  (или uv run python scripts/init_project.py)
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Плейсхолдеры, которые несёт шаблон.
TEMPLATE_SLUG = "max-bot-template"
TEMPLATE_DESCRIPTION = "Шаблон чат-бота для мессенджера MAX (GitHub + Gitea CI/CD)"

# Файлы, в которых заменяются плейсхолдеры. Список явный: слепой обход дерева
# зацепил бы .venv, .git и логи.
TARGET_FILES = (
    "pyproject.toml",
    "docker/docker-compose.local.yml",
    "docker/docker-compose.prod.yml",
    ".gitea/workflows/pipeline.yml",
    "README.md",
)

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,48}[a-z0-9]$")


@dataclass(frozen=True)
class ProjectInfo:
    slug: str
    description: str


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def validate_slug(slug: str) -> str | None:
    """Возвращает текст ошибки или None, если имя пригодно."""
    if not SLUG_PATTERN.match(slug):
        return (
            "Имя должно быть в kebab-case: строчные латинские буквы, цифры и "
            "дефисы, 3–50 символов, начинаться с буквы (например: support-max-bot)"
        )
    if slug == TEMPLATE_SLUG:
        return "Оставлено имя шаблона — задайте своё"
    return None


def collect_info(args: argparse.Namespace) -> ProjectInfo:
    slug = args.name or ""
    while True:
        if not slug:
            slug = ask("Имя проекта (kebab-case)")
        error = validate_slug(slug)
        if error is None:
            break
        print(f"  {error}", file=sys.stderr)
        slug = ""

    description = args.description or ask("Описание бота", f"Чат-бот {slug} для мессенджера MAX")
    return ProjectInfo(slug=slug, description=description)


def replace_in_files(info: ProjectInfo) -> list[Path]:
    """Подставляет имя и описание проекта. Возвращает изменённые файлы."""
    changed: list[Path] = []
    for relative in TARGET_FILES:
        path = ROOT / relative
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        updated = original.replace(TEMPLATE_SLUG, info.slug)
        updated = updated.replace(TEMPLATE_DESCRIPTION, info.description)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


def write_readme(info: ProjectInfo) -> None:
    """Заменяет README шаблона заготовкой под новый проект.

    Исходный README сохраняется как docs/TEMPLATE.md — в нём описано устройство
    шаблона, и терять его при инициализации не хочется.
    """
    readme = ROOT / "README.md"
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    if readme.exists():
        shutil.move(str(readme), str(docs / "TEMPLATE.md"))

    readme.write_text(
        f"""# {info.slug}

{info.description}

## Быстрый старт

```bash
cp .env.example .env      # задать MAX_BOT_TOKEN и ADMIN_IDS
make install
make run
```

Устройство проекта, команды и деплой описаны в [docs/TEMPLATE.md](docs/TEMPLATE.md).
""",
        encoding="utf-8",
    )


def reset_git_history(info: ProjectInfo) -> None:
    """Начинает историю заново одним коммитом.

    user.name и user.email не трогаем — берутся из окружения разработчика.
    """
    git_dir = ROOT / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    subprocess.run(["git", "init", "-b", "Master"], cwd=ROOT, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"chore: инициализация проекта {info.slug}"],
        cwd=ROOT,
        check=True,
    )


def cleanup_template_files() -> None:
    """Удаляет то, что нужно только самому шаблону."""
    for relative in ("scripts/init_project.py",):
        path = ROOT / relative
        if path.exists():
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Инициализация проекта из шаблона")
    parser.add_argument("--name", help="имя проекта в kebab-case")
    parser.add_argument("--description", help="описание бота")
    parser.add_argument(
        "--keep-git",
        action="store_true",
        help="не сбрасывать историю git",
    )
    parser.add_argument(
        "--keep-script",
        action="store_true",
        help="не удалять этот скрипт после инициализации",
    )
    args = parser.parse_args()

    info = collect_info(args)

    print()
    print(f"  Имя:      {info.slug}")
    print(f"  Описание: {info.description}")
    print(f"  История:  {'сохраняется' if args.keep_git else 'начинается заново'}")
    print()
    if ask("Продолжить? (y/n)", "y").lower() not in {"y", "yes", "д", "да"}:
        print("Отменено.")
        return 1

    changed = replace_in_files(info)
    write_readme(info)
    for path in changed:
        print(f"  обновлён {path.relative_to(ROOT)}")

    if not args.keep_script:
        cleanup_template_files()

    if not args.keep_git:
        reset_git_history(info)

    print()
    print("Готово. Дальше:")
    print("  1. cp .env.example .env и заполнить MAX_BOT_TOKEN, ADMIN_IDS")
    print("  2. make install && make run")
    print("  3. заменить разделы меню в src/bot/keyboards/menus.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
