"""Local embeddings via LangChain's Ollama wrapper (spec 002).

Only ever talks to the local Ollama server (default localhost:11434) --
never an external embedding API, per constitution principle 3.
"""

from langchain_ollama import OllamaEmbeddings

EMBEDDING_MODEL = "nomic-embed-text"


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(model=EMBEDDING_MODEL)
