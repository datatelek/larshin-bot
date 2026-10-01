from app.utils import split_telegram_text


def test_short_text_is_not_split() -> None:
    assert split_telegram_text("Короткий ответ", limit=100) == ["Короткий ответ"]


def test_long_text_is_split_without_data_loss() -> None:
    text = " ".join(["слово"] * 100)

    parts = split_telegram_text(text, limit=80)

    assert len(parts) > 1
    assert all(len(part) <= 80 for part in parts)
    assert " ".join(parts) == text
