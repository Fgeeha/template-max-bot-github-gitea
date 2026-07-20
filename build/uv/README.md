# Бинарь uv для закрытого контура

Пайплайн Gitea (`.gitea/workflows/pipeline.yml`) не может скачать uv с
astral.sh — у раннера нет доступа в интернет. Поэтому архив с бинарём лежит
в репозитории, а каждый джоб распаковывает его отсюда.

## Что положить

Файл `uv-x86_64-unknown-linux-gnu.tar.gz` с
[релизной страницы uv](https://github.com/astral-sh/uv/releases):

```bash
curl -L -o build/uv/uv-x86_64-unknown-linux-gnu.tar.gz \
  https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz
```

Архив коммитится, распакованный бинарь — нет (см. `.gitignore`).

Без этого файла джобы `lint`, `test` и `build` в Gitea упадут на шаге
«Распаковать uv». Для GitHub Actions архив не нужен — там uv ставится
через `astral-sh/setup-uv`.
