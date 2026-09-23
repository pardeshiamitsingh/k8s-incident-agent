"""Local reasoning model factory (spec 003).

Ollama only, via LangChain's ChatOllama -- never an external LLM API
(constitution principle 3).
"""

from langchain_ollama import ChatOllama

REASONING_MODEL = "llama3.1:8b"


def get_llm(temperature: float = 0.0) -> ChatOllama:
    """Returns a fresh `ChatOllama` bound to the local reasoning model.
    `temperature=0` by default for reproducible diagnoses."""
    return ChatOllama(model=REASONING_MODEL, temperature=temperature)
