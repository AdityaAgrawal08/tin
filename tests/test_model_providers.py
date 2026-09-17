from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from tin_lite.model_providers import (
    AnthropicModelProvider,
    GeminiModelProvider,
    MessageRole,
    ModelCapability,
    ModelCapabilityError,
    ModelMessage,
    ModelProviderError,
    ModelRequest,
    ModelRoute,
    ModelRouter,
    OpenAIModelProvider,
    ProviderName,
    ReasoningEffort,
    configured_model_router,
)


def _request(*, structured: bool = False) -> ModelRequest:
    return ModelRequest(
        system="Be accurate.",
        messages=(ModelMessage(MessageRole.USER, "Return the answer."),),
        max_output_tokens=200,
        reasoning_effort=ReasoningEffort.HIGH,
        output_schema=(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            }
            if structured
            else None
        ),
    )


class _Closable:
    closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_openai_adapter_uses_responses_and_validates_json_schema() -> None:
    class Responses:
        parameters = None

        async def create(self, **parameters):
            self.parameters = parameters
            return SimpleNamespace(
                output_text='{"answer":"openai"}',
                model="gpt-test",
                id="resp_test",
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=4,
                    total_tokens=14,
                    input_tokens_details=SimpleNamespace(cached_tokens=2),
                    output_tokens_details=SimpleNamespace(reasoning_tokens=1),
                ),
            )

    client = _Closable()
    client.responses = Responses()
    provider = OpenAIModelProvider(api_key="test", client=client)  # noqa: S106

    result = await provider.generate(model="gpt-test", request=_request(structured=True))

    assert result.provider is ProviderName.OPENAI
    assert result.parsed == {"answer": "openai"}
    assert result.usage.cached_input_tokens == 2
    assert client.responses.parameters["reasoning"] == {"effort": "high"}
    assert client.responses.parameters["text"]["format"]["strict"] is True


@pytest.mark.asyncio
async def test_anthropic_adapter_preserves_native_messages_contract() -> None:
    class Messages:
        parameters = None

        async def create(self, **parameters):
            self.parameters = parameters
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"answer":"anthropic"}')],
                model="claude-test",
                _request_id="req_test",
                usage=SimpleNamespace(
                    input_tokens=8,
                    output_tokens=5,
                    cache_creation_input_tokens=1,
                    cache_read_input_tokens=2,
                ),
            )

    client = _Closable()
    client.messages = Messages()
    provider = AnthropicModelProvider(api_key="test", client=client)  # noqa: S106

    result = await provider.generate(model="claude-test", request=_request(structured=True))

    assert result.provider is ProviderName.ANTHROPIC
    assert result.parsed == {"answer": "anthropic"}
    assert result.usage.cached_input_tokens == 2
    assert result.usage.cache_write_input_tokens == 1
    assert result.usage.input_tokens == 11
    assert result.usage.total_tokens == 16
    assert client.messages.parameters["output_config"] == {
        "effort": "high",
        "format": {
            "type": "json_schema",
            "schema": _request(structured=True).output_schema,
        },
    }


@pytest.mark.asyncio
async def test_gemini_adapter_uses_async_official_client() -> None:
    class Models:
        parameters = None

        async def generate_content(self, **parameters):
            self.parameters = parameters
            return SimpleNamespace(
                text='{"answer":"gemini"}',
                model_version="gemini-test",
                response_id="gemini-request",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=7,
                    candidates_token_count=3,
                    total_token_count=11,
                    cached_content_token_count=1,
                    thoughts_token_count=1,
                ),
            )

    class AsyncClient:
        models = Models()
        closed = False

        async def aclose(self):
            self.closed = True

    client = SimpleNamespace(aio=AsyncClient())
    provider = GeminiModelProvider(api_key="test", client=client)  # noqa: S106

    result = await provider.generate(model="gemini-test", request=_request(structured=True))

    assert result.provider is ProviderName.GEMINI
    assert result.parsed == {"answer": "gemini"}
    assert result.usage.reasoning_tokens == 1
    config = client.aio.models.parameters["config"]
    assert config.thinking_config.thinking_level.value == "HIGH"
    assert config.response_mime_type == "application/json"


@pytest.mark.asyncio
async def test_router_uses_only_explicit_route_and_capabilities() -> None:
    class Provider:
        name = ProviderName.OPENAI
        capabilities = frozenset({ModelCapability.TEXT})
        calls = []

        async def generate(self, *, model, request):
            self.calls.append((model, request))
            return SimpleNamespace(provider=self.name, model=model)

        async def close(self):
            pass

    provider = Provider()
    router = ModelRouter(
        providers={ProviderName.OPENAI: provider},
        routes=(
            ModelRoute(
                key="weekly-summary",
                provider=ProviderName.OPENAI,
                model="not-a-prefixed-model-name",
                capabilities=frozenset({ModelCapability.TEXT}),
            ),
        ),
    )

    await router.generate(
        "weekly-summary",
        ModelRequest(messages=(ModelMessage(MessageRole.USER, "Summarize."),)),
    )
    assert provider.calls[0][0] == "not-a-prefixed-model-name"
    with pytest.raises(LookupError, match="not registered"):
        await router.generate("gpt-guessed", _request())
    with pytest.raises(ModelCapabilityError, match="json_schema"):
        await router.generate("weekly-summary", _request(structured=True))


@pytest.mark.asyncio
async def test_switchboard_configuration_reuses_luna_key_for_openai_adapter() -> None:
    settings = SimpleNamespace(
        luna_api_key=SecretStr("openai-test"),
        luna_base_url="https://api.openai.test/v1",
        luna_timeout_seconds=30,
        anthropic_api_key=SecretStr("anthropic-test"),
        anthropic_workspace_id="wrkspc_test",
        gemini_api_key=SecretStr("gemini-test"),
        openrouter_api_key=SecretStr("openrouter-test"),
    )

    router = configured_model_router(settings)  # type: ignore[arg-type]

    assert router.configured_providers == frozenset(
        {ProviderName.OPENAI, ProviderName.ANTHROPIC, ProviderName.GEMINI, ProviderName.OPENROUTER}
    )
    with pytest.raises(LookupError, match="not registered"):
        await router.generate("vendor/model", _request())
    await router.close()


@pytest.mark.parametrize("provider_name", ["openai", "anthropic", "gemini"])
async def test_direct_provider_rejected_output_keeps_usage(provider_name):
    async def create(**kwargs):
        return SimpleNamespace(
            output_text="not JSON",
            text="not JSON",
            content=[SimpleNamespace(type="text", text="not JSON")],
            model="test-model",
            id="response-test",
            _request_id="request-test",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=3,
                total_tokens=13,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
            usage_metadata=SimpleNamespace(total_token_count=13),
        )

    api = SimpleNamespace(create=create)
    client = SimpleNamespace(
        responses=api,
        messages=api,
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=create)),
    )
    provider_class = {
        "openai": OpenAIModelProvider,
        "anthropic": AnthropicModelProvider,
        "gemini": GeminiModelProvider,
    }[provider_name]
    provider = provider_class(api_key="fake", client=client)  # noqa: S106
    with pytest.raises(ModelProviderError) as error:
        await provider.generate(model="test-model", request=_request(structured=True))
    assert error.value.observation.usage.total_tokens == 13
    assert error.value.observation.provider.value == provider_name
