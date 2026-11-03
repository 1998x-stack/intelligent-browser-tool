"""Evidence Radar local-first research workspace (V0.2-B).

Not a multi-tenant cloud execution service. Hosted URL fetch must remain gated.
"""
from .research import ResearchService, ResearchError
from .fetcher import BoundedFetcher, SourcePolicy, FetchError

__all__ = ["ResearchService", "ResearchError", "BoundedFetcher", "SourcePolicy", "FetchError"]
