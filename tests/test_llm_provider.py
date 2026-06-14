from app.services.llm_provider import LLMProvider

def test_search_searxng():
    provider = LLMProvider()

    result = provider._search_searxng("ollama")

    assert isinstance(result, list)
