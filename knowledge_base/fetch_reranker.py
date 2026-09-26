"""One-time setup: download the FlashRank reranker model (spec 014).

Run once (needs network); after that the reranker runs fully offline:

    uv run python -m knowledge_base.fetch_reranker
"""

import logging

from flashrank import Ranker

from .retrieve import rerank_cache_dir, rerank_model_name

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cache = rerank_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    Ranker(model_name=rerank_model_name(), cache_dir=str(cache))
    print(f"reranker model {rerank_model_name()} ready in {cache}")
