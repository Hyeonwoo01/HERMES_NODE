"""Single entry point for LLM calls (Claude via the Anthropic SDK, GPT via the OpenAI SDK).

Same pattern as CreditBridge_AI's ``llm_client``: the provider is chosen by
configuration, callers only use ``parse_json``, the response is constrained to a
JSON schema, and a malformed reply is retried once. Nothing else in the package
imports an SDK directly. SDKs are imported only when a call is actually made,
so the offline demo runs without them.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

Provider = Literal["anthropic", "openai"]
Effort = Literal["low", "medium", "high"]

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
# On a policy decline the API re-runs the request on Anthropic's recommended
# fallback model. The header and the "default" form must be sent together.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """The call failed or the reply never matched the schema."""


class LLMNotConfiguredError(LLMError):
    """No API key or model for the selected provider."""


class LLMRefusalError(LLMError):
    """The model declined the request."""


@dataclass(frozen=True)
class LLMConfig:
    provider: Provider = "anthropic"
    api_key: str = ""
    model: str = ""
    effort: Effort = "medium"
    server_fallback: bool = True  # Claude API only; turn off behind Bedrock/Vertex/proxies
    timeout_s: float = 60.0

    @property
    def resolved_model(self) -> str:
        if self.model:
            return self.model
        return DEFAULT_CLAUDE_MODEL if self.provider == "anthropic" else ""

    @property
    def missing(self) -> list[str]:
        prefix = "ANTHROPIC" if self.provider == "anthropic" else "OPENAI"
        out = [] if self.api_key else [f"{prefix}_API_KEY"]
        if not self.resolved_model:
            out.append(f"{prefix}_MODEL")
        return out

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None = None) -> "LLMConfig":
        """Build from st.secrets-like mappings, falling back to environment variables."""
        values = dict(values or {})

        def get(key: str, default: str = "") -> str:
            v = values.get(key, os.environ.get(key, default))
            return "" if v is None else str(v).strip()

        provider = get("LLM_PROVIDER", "anthropic").lower()
        if provider not in ("anthropic", "openai"):
            raise ValueError(f"LLM_PROVIDER must be 'anthropic' or 'openai', got {provider!r}")
        key, model = (("ANTHROPIC_API_KEY", "CLAUDE_MODEL") if provider == "anthropic"
                      else ("OPENAI_API_KEY", "OPENAI_MODEL"))
        effort = get("LLM_EFFORT", "medium").lower()
        return cls(provider=provider, api_key=get(key), model=get(model),  # type: ignore[arg-type]
                   effort=effort if effort in ("low", "medium", "high") else "medium",  # type: ignore[arg-type]
                   server_fallback=get("CLAUDE_SERVER_FALLBACK", "true").lower() != "false")


@dataclass(frozen=True)
class _Reply:
    text: str
    truncated: bool
    model: str


class LLMClient:
    def __init__(self, config: LLMConfig, client: Any | None = None) -> None:
        """``client`` is a fake SDK client for tests; otherwise the SDK is built on first use."""
        self.config = config
        self._client = client

    @property
    def configured(self) -> bool:
        return not self.config.missing or self._client is not None

    @property
    def model(self) -> str:
        return self.config.resolved_model

    def _sdk(self) -> Any:
        if self._client is None:
            if self.config.missing:
                raise LLMNotConfiguredError("not configured: " + ", ".join(self.config.missing))
            if self.config.provider == "openai":
                import openai

                self._client = openai.OpenAI(api_key=self.config.api_key, max_retries=2,
                                             timeout=self.config.timeout_s)
            else:
                import anthropic

                self._client = anthropic.Anthropic(api_key=self.config.api_key, max_retries=2,
                                                   timeout=self.config.timeout_s)
        return self._client

    def parse_json(self, prompt: str, schema: dict, name: str, *, system: str = "",
                   max_tokens: int = 16000, validate: Callable[[dict], None] | None = None) -> tuple[dict, str]:
        """Send the prompt, return (parsed JSON, model that answered). Retries once on a bad reply."""
        call = self._call_openai if self.config.provider == "openai" else self._call_anthropic
        last: Exception | None = None
        for attempt in range(2):
            reply = call(prompt, system, schema, name, max_tokens)
            try:
                if reply.truncated:
                    raise ValueError("output truncated at max_tokens")
                data = json.loads(reply.text)
                if not isinstance(data, dict):
                    raise ValueError("reply is not a JSON object")
                if validate:
                    validate(data)
                return data, reply.model
            except ValueError as exc:  # json.JSONDecodeError is a ValueError
                last = exc
                logger.warning("llm reply failed validation (attempt %d): %s", attempt + 1, exc)
        raise LLMError(f"output failed validation twice: {last}")

    def _call_anthropic(self, prompt: str, system: str, schema: dict, name: str, max_tokens: int) -> _Reply:
        import anthropic

        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "output_config": {"effort": self.config.effort, "format": {"type": "json_schema", "schema": schema}},
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            params["system"] = system
        if self.config.server_fallback:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        try:
            response = self._sdk().beta.messages.create(**params)
        except anthropic.APIError as exc:
            raise LLMError(f"Claude API error: {type(exc).__name__}") from exc
        if response.stop_reason == "refusal":
            raise LLMRefusalError("the model declined the request")
        text = "".join(block.text for block in response.content if block.type == "text")
        return _Reply(text, response.stop_reason == "max_tokens", response.model)

    def _call_openai(self, prompt: str, system: str, schema: dict, name: str, max_tokens: int) -> _Reply:
        import openai

        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        params: dict[str, Any] = {
            "model": self.model,
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
            "messages": messages,
        }
        try:
            response = self._sdk().chat.completions.create(**params)
        except openai.APIError as exc:
            raise LLMError(f"OpenAI API error: {type(exc).__name__}") from exc
        choice = response.choices[0]
        if getattr(choice.message, "refusal", None) or choice.finish_reason == "content_filter":
            raise LLMRefusalError("the model declined the request")
        return _Reply(choice.message.content or "", choice.finish_reason == "length", response.model)
