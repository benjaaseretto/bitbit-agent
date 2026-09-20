"""DeepSeek LLM with a working thinking toggle.

Pipecat 1.11's DeepSeekLLMService defines ``_build_chat_completion_params``
but BaseOpenAILLMService calls ``build_chat_completion_params`` — so thinking
never reaches the API. V4 Flash then stays in default thinking mode and
rejects ``tool_choice=required`` with HTTP 400, which kills the pipeline.
"""
from __future__ import annotations

from pipecat.adapters.services.open_ai_adapter import OpenAILLMInvocationParams
from pipecat.services.deepseek.llm import DeepSeekLLMService
from pipecat.utils.types import is_given


class BitbitDeepSeekLLMService(DeepSeekLLMService):
    """DeepSeekLLMService that actually sends ``thinking`` in ``extra_body``."""

    def build_chat_completion_params(
        self, params_from_context: OpenAILLMInvocationParams
    ) -> dict:
        params = {
            "model": self._settings.model,
            "stream": True,
            "stream_options": {"include_usage": True},
            "frequency_penalty": self._settings.frequency_penalty,
            "presence_penalty": self._settings.presence_penalty,
            "temperature": self._settings.temperature,
            "top_p": self._settings.top_p,
            "max_tokens": self._settings.max_tokens,
        }
        thinking = self._settings.thinking
        if is_given(thinking) and thinking is not None:
            dump = (
                thinking.model_dump(exclude_none=True)
                if hasattr(thinking, "model_dump")
                else thinking
            )
            params["extra_body"] = {"thinking": dump}

        params.update(params_from_context)
        params.update(self._settings.extra)
        # Drop Nones so the OpenAI client doesn't send junk DeepSeek rejects.
        return {k: v for k, v in params.items() if v is not None}
