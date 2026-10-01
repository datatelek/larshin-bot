from __future__ import annotations

import base64
import hashlib
import hmac

from openai import AsyncOpenAI

from app.config import AppConfig
from app.prompts import image_prompt, instructions_for


class OpenAIService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.client = AsyncOpenAI(api_key=config.openai_api_key)

    async def generate_text(self, user_id: int, mode: str, prompt: str) -> str:
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
        return output

    async def generate_image(self, prompt: str, size: str) -> bytes:
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
        return base64.b64decode(response.data[0].b64_json)

    async def close(self) -> None:
        await self.client.close()
