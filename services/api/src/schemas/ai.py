from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Hit(BaseModel):
    id: Optional[str] = None
    document_id: Optional[int] = None
    chunk_idx: Optional[int] = None
    text: Optional[str] = None
    summary: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)
    kg: Optional[Any] = None
    score: Optional[float] = None
    query_variant: Optional[str] = None
    source_type: Optional[str] = None
    source_tier: Optional[str] = None


class Intent(BaseModel):
    name: str
    slots: Dict[str, Any] = Field(default_factory=dict)


class AnalysisResult(BaseModel):
    intent: Intent
    query_variants: List[str] = Field(default_factory=list)
    alias_filters: Dict[str, Any] = Field(default_factory=dict)
    entity_hints: Dict[str, Any] = Field(default_factory=dict)
    entity_resolution: Dict[str, Any] = Field(default_factory=dict)
    followup_context: Dict[str, Any] = Field(default_factory=dict)
    attachment_context: Dict[str, Any] = Field(default_factory=dict)
    url_lookup: Dict[str, Any] = Field(default_factory=dict)
    url_inputs: List[str] = Field(default_factory=list)
    primary_url: Optional[str] = None
    url_input_source: Optional[str] = None
    lookup_goal: Optional[str] = None
    retrieval_query: Optional[str] = None
    prompt_category: Optional[str] = None
    needs_authoritative_sources: bool = False
    authoritative_reason: Optional[str] = None


class RetrievalResult(BaseModel):
    hits: List[Hit] = Field(default_factory=list)
    cerp_products: List[Dict[str, Any]] = Field(default_factory=list)
    errors: Dict[str, str] = Field(default_factory=dict)
    internal_hits: List[Hit] = Field(default_factory=list)
    external_hits: List[Hit] = Field(default_factory=list)
    selected_hits: List[Hit] = Field(default_factory=list)
    retrieval_errors: Dict[str, str] = Field(default_factory=dict)
    source_tiers: Dict[str, str] = Field(default_factory=dict)
    external_search: Dict[str, Any] = Field(default_factory=dict)
    retrieval_snapshot: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    ok: bool = True
    kind: str = "chat"
    intent: Intent
    answer: Dict[str, Any] = Field(default_factory=dict)
    context: List[Hit] = Field(default_factory=list)
    content: str = ""
    language: Optional[str] = None
    project: Optional[Dict[str, Any]] = None
    store: Optional[Dict[str, Any]] = None
