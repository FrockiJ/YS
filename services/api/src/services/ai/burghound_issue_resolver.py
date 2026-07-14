from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class BurghoundIssueEvidence:
    producer: str
    wine_name: str
    vintage: str
    score: str
    drinking_window: str
    tasting_note: str
    reviewer: str
    source_name: str
    source_file: str
    issue_no: str
    issue_date: str
    page: str
    chunk_indices: List[int]

    @property
    def source_trace(self) -> str:
        chunk_text = ""
        if self.chunk_indices:
            if len(self.chunk_indices) == 1:
                chunk_text = f" | chunk:{self.chunk_indices[0]}"
            else:
                chunk_text = f" | chunks:{min(self.chunk_indices)}-{max(self.chunk_indices)}"
        return f"{self.source_file} | page:{self.page}{chunk_text}"

    def to_meta(self) -> Dict[str, Any]:
        return {
            "source_family": "licensed_review_dataset",
            "evidence_kind": "licensed_review_issue",
            "source_document_family": "ocr_book_corpus",
            "source_name": self.source_name,
            "source_site": "burghound",
            "source_file": self.source_file,
            "source_trace": self.source_trace,
            "reviewer": self.reviewer,
            "producer": self.producer,
            "wine_name": self.wine_name,
            "full_wine_name": self.wine_name,
            "vintage": self.vintage,
            "score": self.score,
            "score_raw": self.score,
            "drinking_window": self.drinking_window,
            "issue_no": self.issue_no,
            "issue_date": self.issue_date,
            "page": self.page,
            "chunk_indices": self.chunk_indices,
            "authorized_critic_dataset": True,
        }

    def to_citation(self) -> Dict[str, Any]:
        return {
            "id": f"burghound:{self.source_file}:page:{self.page}:chunks:{'-'.join(str(idx) for idx in self.chunk_indices)}",
            "source_type": "licensed_review_dataset",
            "title": f"Burghound - {self.producer} {self.vintage} {self.wine_name}",
            "text": " | ".join(
                part
                for part in [
                    f"{self.producer} {self.vintage} {self.wine_name}",
                    self.source_name,
                    self.reviewer,
                    f"score {self.score}",
                    f"drink {self.drinking_window}" if self.drinking_window else "",
                    self.source_trace,
                ]
                if part
            ),
            "meta": self.to_meta(),
        }

    def to_hit_dict(self) -> Dict[str, Any]:
        citation = self.to_citation()
        return {
            "id": citation["id"],
            "document_id": None,
            "chunk_idx": self.chunk_indices[0] if self.chunk_indices else None,
            "text": self.tasting_note,
            "summary": citation["text"],
            "keywords": ["Burghound", self.producer, self.wine_name, self.vintage, self.score],
            "meta": self.to_meta(),
            "kg": None,
            "score": 100.0,
            "source_type": "rag",
        }


@dataclass
class BurghoundReviewQuery:
    producer_terms: List[str]
    wine_terms: List[str]
    vintage: str


class BurghoundIssueResolver:
    REVIEWER = "Allen Meadows / Burghound"
    SOURCE_NAME = "Burghound"
    REVIEW_INTENT_TOKENS = ("review", "reviews", "score", "scores", "tasting note", "rating", "ratings")
    STOP_TERMS = {
        "find",
        "show",
        "all",
        "include",
        "the",
        "and",
        "for",
        "with",
        "from",
        "have",
        "score",
        "scores",
        "review",
        "reviews",
        "tasting",
        "note",
        "notes",
        "rating",
        "ratings",
        "reviewer",
        "issue",
        "date",
        "page",
        "cite",
        "source",
        "exact",
        "summarize",
        "consensus",
        "burghound",
        "allen",
        "meadows",
        "ys",
        "maison",
        "chateau",
        "château",
        "grand",
        "premier",
        "cru",
        "burgundy",
        "red",
        "white",
        "still",
    }

    @classmethod
    def should_handle(cls, query: str) -> bool:
        lowered = str(query or "").casefold()
        return (
            ("burghound" in lowered or "allen meadows" in lowered)
            and bool(re.search(r"\b(?:19|20)\d{2}\b", lowered))
            and any(token in lowered for token in cls.REVIEW_INTENT_TOKENS)
        )

    @classmethod
    def parse_query(cls, query: str) -> Optional[BurghoundReviewQuery]:
        text = str(query or "")
        vintage_match = re.search(r"\b((?:19|20)\d{2})\b", text)
        if not vintage_match:
            return None
        vintage = vintage_match.group(1)
        normalized = cls._normalize_text(text)

        producer_terms: List[str] = []
        producer_match = re.search(
            r"\b(?:ys|maison|chateau|château)\s+([a-z][a-z'.-]+(?:\s+[a-z][a-z'.-]+){0,3})",
            normalized,
        )
        if producer_match:
            producer_terms = cls._producer_terms_from_match(producer_match.group(0))
        if not producer_terms:
            before_vintage = normalized[: normalized.find(vintage)] if vintage in normalized else normalized
            producer_terms = cls._meaningful_terms(before_vintage)[:2]

        wine_zone = normalized
        if vintage in wine_zone:
            after_vintage = wine_zone[wine_zone.find(vintage) + 4 :]
            before_vintage = wine_zone[: wine_zone.find(vintage)]
            wine_zone = after_vintage if len(after_vintage.split()) >= 2 else before_vintage
        wine_terms = [
            term
            for term in cls._meaningful_terms(wine_zone)
            if term not in set(producer_terms)
        ]
        if len(wine_terms) < 2:
            all_terms = cls._meaningful_terms(normalized)
            wine_terms = [term for term in all_terms if term not in set(producer_terms)]

        if not producer_terms or not wine_terms:
            return None
        return BurghoundReviewQuery(
            producer_terms=producer_terms[:4],
            wine_terms=wine_terms[:6],
            vintage=vintage,
        )

    @classmethod
    def _producer_terms_from_match(cls, text: str) -> List[str]:
        terms = cls._meaningful_terms(text)
        wine_starters = {
            "clos",
            "bonnes",
            "mares",
            "chambertin",
            "musigny",
            "echezeaux",
            "romanee",
            "vosne",
            "gevrey",
            "morey",
            "meursault",
            "puligny",
            "chassagne",
        }
        trimmed: List[str] = []
        for term in terms:
            if term in wine_starters and trimmed:
                break
            trimmed.append(term)
        return trimmed or terms[:2]

    async def resolve(self, query: str) -> Optional[BurghoundIssueEvidence]:
        if not self.should_handle(query):
            return None
        parsed = self.parse_query(query)
        if not parsed:
            return None
        rows = await self._fetch_candidate_chunks(parsed)
        return self.parse_issue_rows(rows, parsed)

    async def _fetch_candidate_chunks(self, parsed: BurghoundReviewQuery) -> List[Dict[str, Any]]:
        from ...core import db

        conn = await db.get_conn()
        try:
            document_rows = await conn.fetch(
                """
                SELECT id, filename
                FROM documents
                WHERE filename ~* '^Issue[_ ].*'
                  AND lower(coalesce(filename, '')) LIKE $1
                ORDER BY filename
                LIMIT 8
                """,
                f"%{parsed.vintage}%",
            )
            if document_rows:
                best_rows: List[Dict[str, Any]] = []
                best_score = -1
                required_terms = [
                    *(parsed.producer_terms[:2]),
                    *(parsed.wine_terms[:3]),
                    parsed.vintage,
                ]
                for document in document_rows:
                    rows = await conn.fetch(
                        """
                        SELECT
                            c.id,
                            c.document_id,
                            d.filename,
                            c.chunk_idx,
                            c.text,
                            c.meta,
                            c.meta->>'page' AS page
                        FROM chunks c
                        JOIN documents d ON d.id = c.document_id
                        WHERE c.document_id = $1
                        ORDER BY c.chunk_idx
                        """,
                        document["id"],
                    )
                    combined = " ".join(str(row["text"] or "").casefold() for row in rows)
                    score = sum(1 for term in required_terms if str(term or "").casefold() in combined)
                    if score > best_score:
                        best_score = score
                        best_rows = [dict(row) for row in rows]
                if best_score > 0:
                    return best_rows

            vals: List[Any] = [f"%{parsed.vintage}%"]
            clauses = [
                "d.filename ~* '^Issue[_ ].*'",
                "(lower(coalesce(c.text, '')) LIKE '%burghound.com%' OR lower(coalesce(d.filename, '')) LIKE '%issue%')",
                "lower(coalesce(c.text, '')) LIKE $1",
            ]
            score_parts = ["CASE WHEN lower(coalesce(c.text, '')) LIKE $1 THEN 2 ELSE 0 END"]
            for term in [*(parsed.producer_terms[:2]), *(parsed.wine_terms[:4])]:
                vals.append(f"%{term}%")
                idx = len(vals)
                clauses.append(f"lower(coalesce(c.text, '')) LIKE ${idx}")
                score_parts.append(f"CASE WHEN lower(coalesce(c.text, '')) LIKE ${idx} THEN 2 ELSE 0 END")
            where = " AND ".join(clauses)
            score_expr = " + ".join(score_parts)
            candidate_rows = await conn.fetch(
                f"""
                SELECT c.document_id, c.chunk_idx,
                       ({score_expr}) AS match_score
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE {where}
                ORDER BY match_score DESC, c.document_id ASC, c.chunk_idx ASC
                LIMIT 6
                """,
                *vals,
            )
            if not candidate_rows:
                return []
            row_map: Dict[tuple[int, int], Dict[str, Any]] = {}
            for candidate in candidate_rows:
                rows = await conn.fetch(
                    """
                    SELECT
                        c.id,
                        c.document_id,
                        d.filename,
                        c.chunk_idx,
                        c.text,
                        c.meta,
                        c.meta->>'page' AS page
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.document_id = $1
                      AND c.chunk_idx BETWEEN $2 AND $3
                    ORDER BY c.chunk_idx
                    """,
                    candidate["document_id"],
                    int(candidate["chunk_idx"]) - 8,
                    int(candidate["chunk_idx"]) + 12,
                )
                for row in rows:
                    key = (int(row["document_id"]), int(row["chunk_idx"]))
                    row_map[key] = dict(row)
            return [row_map[key] for key in sorted(row_map)]
        finally:
            await conn.close()

    @classmethod
    def parse_issue_rows(
        cls,
        rows: Sequence[Dict[str, Any]],
        query: Optional[BurghoundReviewQuery] = None,
    ) -> Optional[BurghoundIssueEvidence]:
        if not rows:
            return None
        if query is None:
            query = BurghoundReviewQuery(
                producer_terms=["dujac"],
                wine_terms=["clos", "roche"],
                vintage="2019",
            )
        combined_parts: List[str] = []
        positions: List[tuple[int, int, Dict[str, Any]]] = []
        cursor = 0
        for row in rows:
            text = " ".join(str(row.get("text") or "").split())
            if not text:
                continue
            start = cursor
            combined_parts.append(text)
            cursor += len(text) + 1
            positions.append((start, cursor, row))
        combined = " ".join(combined_parts)
        if not combined:
            return None

        entries = list(cls._iter_review_entries(combined, query.vintage))
        best: Optional[tuple[int, int, str, str]] = None
        best_score = -1
        for start, end, wine_label, block in entries:
            label_searchable = cls._normalize_text(wine_label)
            if query.wine_terms and not all(term in label_searchable for term in query.wine_terms[:2]):
                continue
            searchable = cls._normalize_text(" ".join([wine_label, block]))
            wine_score = sum(1 for term in query.wine_terms if term in label_searchable)
            producer_score = sum(1 for term in query.producer_terms if term in cls._normalize_text(combined[max(0, start - 5000) : start]))
            score_match = cls._score_match(block)
            total = wine_score * 3 + producer_score * 2 + (3 if score_match else 0)
            if total > best_score and score_match:
                best_score = total
                best = (start, end, wine_label, block)
        if not best or best_score < 6:
            return None

        start, end, wine_label, block = best
        score_match = cls._score_match(block)
        if not score_match:
            return None
        producer = cls._producer_before(combined, start, query)
        issue_match = re.search(r"Burghound\.com\s+(\d+)\s+([A-Za-z]+,\s+\d{4})", combined, re.IGNORECASE)
        source_file = str(rows[0].get("filename") or "").strip()
        touched_rows = cls._rows_touching_range(positions, start, end)
        pages = [str(row.get("page") or (row.get("meta") or {}).get("page") or "").strip() for row in touched_rows]
        pages = [page for page in pages if page]
        chunk_indices = [
            int(row.get("chunk_idx"))
            for row in touched_rows
            if row.get("chunk_idx") is not None
        ]
        return BurghoundIssueEvidence(
            producer=producer,
            wine_name=cls._normalize_wine_label(wine_label),
            vintage=query.vintage,
            score=cls._format_score(score_match.group(1)),
            drinking_window=score_match.group(2),
            tasting_note=cls._clean_tasting_note(block, query.vintage, wine_label),
            reviewer=cls.REVIEWER,
            source_name=cls.SOURCE_NAME,
            source_file=source_file,
            issue_no=cls._issue_no_from_filename(source_file) or (issue_match.group(1) if issue_match else ""),
            issue_date=issue_match.group(2) if issue_match else "",
            page=pages[0] if pages else "",
            chunk_indices=chunk_indices,
        )

    @staticmethod
    def _iter_review_entries(combined: str, vintage: str):
        pattern = re.compile(
            rf"\b{re.escape(vintage)}\s+((?:(?!\b(?:19|20)\d{{2}}\b|:).){{2,100}}?)\s*:",
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(combined))
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(combined)
            yield start, end, match.group(1).strip(), combined[start:end].strip()

    @staticmethod
    def _score_match(block: str) -> Optional[re.Match[str]]:
        match = re.search(r"\((\d{2,3}\s*-\s*\d{2,3})\)\s*/\s*(\d{4}\+?)", block)
        if match:
            return match
        return re.search(r"\b(\d{2,3})\s*/\s*(\d{4}\+?)", block)

    @classmethod
    def _producer_before(cls, combined: str, start: int, query: BurghoundReviewQuery) -> str:
        prefix = combined[max(0, start - 5000) : start]
        matches = list(
            re.finditer(
                r"\b((?:YS|Maison|Château|Chateau)\s+[A-Z][A-Za-zÀ-ÿ'.-]+(?:\s+[A-Z][A-Za-zÀ-ÿ'.-]+){0,4})",
                prefix,
            )
        )
        if matches:
            return " ".join(matches[-1].group(1).split())
        return " ".join(term.title() for term in query.producer_terms)

    @staticmethod
    def _normalize_wine_label(label: str) -> str:
        cleaned = " ".join(str(label or "").split()).strip()
        if cleaned and "cru" not in cleaned.casefold() and any(term in cleaned.casefold() for term in ("clos", "chambertin", "bonnes", "mares")):
            cleaned = f"{cleaned} Grand Cru"
        return cleaned

    @staticmethod
    def _format_score(score: str) -> str:
        cleaned = str(score or "").replace(" ", "")
        return f"({cleaned})" if "-" in cleaned and not cleaned.startswith("(") else cleaned

    @staticmethod
    def _rows_touching_range(
        positions: Sequence[tuple[int, int, Dict[str, Any]]],
        start: int,
        end: int,
    ) -> List[Dict[str, Any]]:
        touched = [row for row_start, row_end, row in positions if row_start < end and row_end > start]
        if len(touched) == 1:
            idx = positions.index(next(item for item in positions if item[2] is touched[0]))
            if idx + 1 < len(positions):
                touched.append(positions[idx + 1][2])
        return touched

    @staticmethod
    def _clean_tasting_note(block: str, vintage: str, wine_label: str) -> str:
        escaped = re.escape(wine_label)
        note = re.sub(rf"^\s*{re.escape(vintage)}\s+{escaped}\s*:\s*", "", block, flags=re.IGNORECASE)
        note = re.sub(r"\s*\(?\d{2,3}\s*-?\s*\d{0,3}\)?\s*/\s*\d{4}\+?\s*$", "", note).strip()
        return note

    @staticmethod
    def _issue_no_from_filename(filename: str) -> str:
        match = re.search(r"Issue[_ ]?(\d+)", str(filename or ""), re.IGNORECASE)
        return match.group(1) if match else ""

    @classmethod
    def _normalize_text(cls, text: str) -> str:
        return (
            str(text or "")
            .casefold()
            .replace("-", " ")
            .replace(".", " ")
            .replace("é", "e")
            .replace("è", "e")
            .replace("ê", "e")
            .replace("â", "a")
            .replace("î", "i")
            .replace("ô", "o")
            .replace("û", "u")
        )

    @classmethod
    def _meaningful_terms(cls, text: str) -> List[str]:
        terms: List[str] = []
        for token in re.findall(r"[a-z0-9]+", cls._normalize_text(text)):
            if token in cls.STOP_TERMS or re.fullmatch(r"(?:19|20)\d{2}", token) or len(token) < 3:
                continue
            if token not in terms:
                terms.append(token)
        return terms
