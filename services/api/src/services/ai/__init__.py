__all__ = [
    "AnalysisService",
    "ExternalSearchService",
    "GenerationService",
    "GroundingService",
    "ChatOrchestrator",
    "RetrievalService",
]


def __getattr__(name):
    if name == "AnalysisService":
        from .analysis import AnalysisService
        return AnalysisService
    if name == "ExternalSearchService":
        from .external_search import ExternalSearchService
        return ExternalSearchService
    if name == "GenerationService":
        from .generation import GenerationService
        return GenerationService
    if name == "GroundingService":
        from .grounding import GroundingService
        return GroundingService
    if name == "ChatOrchestrator":
        from .orchestrator import ChatOrchestrator
        return ChatOrchestrator
    if name == "RetrievalService":
        from .retrieval import RetrievalService
        return RetrievalService
    raise AttributeError(name)
