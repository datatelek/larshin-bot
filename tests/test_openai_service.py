from types import SimpleNamespace

from app.openai_service import (
    calculate_image_cost_microusd,
    calculate_text_cost_microusd,
)


def test_calculate_text_cost_uses_cached_and_regular_tokens() -> None:
    usage = SimpleNamespace(
        input_tokens=2_000,
        output_tokens=1_000,
        input_tokens_details=SimpleNamespace(cached_tokens=500, cache_write_tokens=0),
    )

    assert calculate_text_cost_microusd(usage) == 1_510


def test_calculate_image_cost_uses_text_image_and_output_tokens() -> None:
    usage = SimpleNamespace(
        output_tokens=196,
        input_tokens_details=SimpleNamespace(text_tokens=100, image_tokens=0),
    )

    assert calculate_image_cost_microusd(usage) == 6_380
