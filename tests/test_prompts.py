from app.prompts import image_prompt, instructions_for


def test_semantics_prompt_forbids_fake_frequency() -> None:
    instructions = instructions_for("semantics")

    assert "Не придумывай показы" in instructions
    assert "без частотности" in instructions


def test_image_prompt_contains_user_task() -> None:
    prompt = image_prompt("Баннер для SEO-аудита")

    assert "Баннер для SEO-аудита" in prompt
    assert "Создай одно" in prompt
