from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from openai import AsyncOpenAI

from app.config import AppConfig
from app.prompts import image_prompt, instructions_for

TEXT_INPUT_USD_PER_MILLION = Decimal("0.20")
TEXT_CACHED_INPUT_USD_PER_MILLION = Decimal("0.02")
TEXT_CACHE_WRITE_USD_PER_MILLION = Decimal("0.25")
TEXT_OUTPUT_USD_PER_MILLION = Decimal("1.20")

IMAGE_TEXT_INPUT_USD_PER_MILLION = Decimal("5.00")
IMAGE_INPUT_USD_PER_MILLION = Decimal("8.00")
IMAGE_OUTPUT_USD_PER_MILLION = Decimal("30.00")

TEXT_RESERVATION_MICROUSD = 20_000
IMAGE_RESERVATION_MICROUSD = 50_000


@dataclass(frozen=True, slots=True)
class TextResult:
    value: str
    cost_microusd: int


@dataclass(frozen=True, slots=True)
class ImageResult:
    value: bytes
    cost_microusd: int


def _token_cost_microusd(tokens: int, rate_per_million: Decimal) -> Decimal:
    return Decimal(tokens) * rate_per_million


def _round_cost_microusd(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_CEILING))


def calculate_text_cost_microusd(usage) -> int:
    details = usage.input_tokens_details
    cached = max(int(getattr(details, "cached_tokens", 0)), 0)
    cache_write = max(int(getattr(details, "cache_write_tokens", 0)), 0)
    regular = max(int(usage.input_tokens) - cached - cache_write, 0)
    cost = (
        _token_cost_microusd(regular, TEXT_INPUT_USD_PER_MILLION)
        + _token_cost_microusd(cached, TEXT_CACHED_INPUT_USD_PER_MILLION)
        + _token_cost_microusd(cache_write, TEXT_CACHE_WRITE_USD_PER_MILLION)
        + _token_cost_microusd(int(usage.output_tokens), TEXT_OUTPUT_USD_PER_MILLION)
    )
    return _round_cost_microusd(cost)


def calculate_image_cost_microusd(usage) -> int:
    details = usage.input_tokens_details
    text_input = max(int(getattr(details, "text_tokens", 0)), 0)
    image_input = max(int(getattr(details, "image_tokens", 0)), 0)
    cost = (
        _token_cost_microusd(text_input, IMAGE_TEXT_INPUT_USD_PER_MILLION)
        + _token_cost_microusd(image_input, IMAGE_INPUT_USD_PER_MILLION)
        + _token_cost_microusd(int(usage.output_tokens), IMAGE_OUTPUT_USD_PER_MILLION)
    )
    return _round_cost_microusd(cost)


class OpenAIService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.client = AsyncOpenAI(api_key=config.openai_api_key)

    async def generate_text(
        self, user_id: int, mode: str, prompt: str
    ) -> TextResult:
        safety_identifier = hmac.new(
            self.config.openai_api_key.encode("utf-8"),
            f"telegram:{user_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        response = await self.client.responses.create(
            model=self.config.text_model,
            instructions=instructions_for(mode),
            input=prompt,
            max_output_tokens=self.config.max_output_tokens,
            safety_identifier=safety_identifier,
            store=False,
        )
        output = response.output_text.strip()
        if not output:
            raise RuntimeError("OpenAI API вернул пустой текстовый ответ")
        cost = (
            calculate_text_cost_microusd(response.usage)
            if response.usage is not None
            else TEXT_RESERVATION_MICROUSD
        )
        return TextResult(output, cost)

    async def generate_image(self, prompt: str, size: str) -> ImageResult:
        response = await self.client.images.generate(
            model=self.config.image_model,
            prompt=image_prompt(prompt),
            n=1,
            size=size,
            quality=self.config.image_quality,
            output_format="png",
        )
        if not response.data or not response.data[0].b64_json:
            raise RuntimeError("OpenAI API не вернул изображение")
        cost = (
            calculate_image_cost_microusd(response.usage)
            if response.usage is not None
            else IMAGE_RESERVATION_MICROUSD
        )
        return ImageResult(base64.b64decode(response.data[0].b64_json), cost)

    async def close(self) -> None:
        await self.client.close()
