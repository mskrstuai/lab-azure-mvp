"""
Search Memory Models

Data structures for tracking search queries and their results within an agent session.
"""

from datetime import datetime
from typing import List, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, PrivateAttr, ConfigDict

from .search import SearchResponse, SearchResult


class SearchRecord(BaseModel):
    """A single search operation record."""

    record_id: str = Field(default_factory=lambda: str(uuid4()))

    search_query: str
    function_name: str
    function_arguments: Dict = Field(default_factory=dict)

    results: SearchResponse = Field(
        default_factory=lambda: SearchResponse(results=[], facets=None, total_count=0)
    )

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    result_count: int = 0

    model_config = ConfigDict(arbitrary_types_allowed=True)


class UserTurnSearches(BaseModel):
    """All searches triggered by a single user message/turn."""

    turn_id: str = Field(default_factory=lambda: str(uuid4()))
    user_message: str
    searches: List[SearchRecord] = Field(default_factory=list)
    was_clarification_only: bool = False
    timestamp: datetime = Field(default_factory=datetime.now)

    @property
    def total_results(self) -> int:
        return sum(s.result_count for s in self.searches)

    @property
    def search_count(self) -> int:
        return len(self.searches)

    def add_search(self, record: SearchRecord) -> None:
        self.searches.append(record)

    def get_all_results(self) -> List[SearchResult]:
        all_results = []
        for search in self.searches:
            all_results.extend(search.results.results)
        return all_results

    def get_all_results_deduplicated(self) -> List[SearchResult]:
        seen: Dict[str, SearchResult] = {}

        for search in self.searches:
            for result in search.results.results:
                article_id = result.article_id
                if article_id is None:
                    continue

                if article_id not in seen:
                    seen[article_id] = result
                else:
                    current_score = result.final_score or result.effective_search_score
                    existing_score = (
                        seen[article_id].final_score
                        or seen[article_id].effective_search_score
                    )
                    if current_score > existing_score:
                        seen[article_id] = result

        return list(seen.values())

    def get_all_product_ids(self) -> List[str]:
        ids = set()
        for search in self.searches:
            for result in search.results.results:
                if result.article_id:
                    ids.add(result.article_id)
        return list(ids)


class SearchMemory(BaseModel):
    """Session-level memory for all search operations."""

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: Optional[str] = None

    turns: List[UserTurnSearches] = Field(default_factory=list)

    _current_turn: Optional[UserTurnSearches] = PrivateAttr(default=None)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def start_turn(self, user_message: str) -> UserTurnSearches:
        self._current_turn = UserTurnSearches(user_message=user_message)
        return self._current_turn

    def end_turn(
        self, was_clarification_only: bool = False
    ) -> Optional[UserTurnSearches]:
        if self._current_turn is None:
            return None

        self._current_turn.was_clarification_only = (
            was_clarification_only or len(self._current_turn.searches) == 0
        )
        self.turns.append(self._current_turn)
        completed_turn = self._current_turn
        self._current_turn = None
        return completed_turn

    def record_search(
        self,
        search_query: str,
        function_name: str,
        function_arguments: Dict,
        results: SearchResponse,
    ) -> Optional[SearchRecord]:
        if self._current_turn is None:
            return None

        record = SearchRecord(
            search_query=search_query,
            function_name=function_name,
            function_arguments=function_arguments,
            results=results,
            result_count=len(results.results) if results else 0,
        )

        self._current_turn.add_search(record)
        return record

    @property
    def current_turn(self) -> Optional[UserTurnSearches]:
        return self._current_turn

    @property
    def last_turn(self) -> Optional[UserTurnSearches]:
        return self.turns[-1] if self.turns else None

    @property
    def total_searches(self) -> int:
        return sum(turn.search_count for turn in self.turns)

    def get_current_turn_results(self) -> List[SearchResult]:
        if self._current_turn is None:
            return []
        return self._current_turn.get_all_results()

    def get_current_turn_results_deduplicated(self) -> List[SearchResult]:
        if self._current_turn is None:
            return []
        return self._current_turn.get_all_results_deduplicated()

    def get_recent_product_ids(self, n_turns: int = 3) -> List[str]:
        ids = set()
        for turn in self.turns[-n_turns:]:
            ids.update(turn.get_all_product_ids())
        return list(ids)

    def get_search_history(self) -> List[Dict]:
        history = []
        for turn in self.turns:
            turn_summary = {
                "turn_id": turn.turn_id,
                "user_message": turn.user_message,
                "timestamp": turn.timestamp.isoformat(),
                "was_clarification_only": turn.was_clarification_only,
                "searches": [
                    {
                        "function": s.function_name,
                        "query": s.search_query,
                        "result_count": s.result_count,
                        "is_reranked": s.results.is_reranked if s.results else False,
                    }
                    for s in turn.searches
                ],
            }
            history.append(turn_summary)
        return history

    def to_context_string(self, n_turns: int = 3) -> str:
        if not self.turns:
            return "No previous searches in this session."

        recent = self.turns[-n_turns:]
        lines = ["Recent search activity:"]

        for turn in recent:
            if turn.was_clarification_only:
                lines.append(
                    f"- User: '{turn.user_message}' → (clarification, no search)"
                )
            else:
                for search in turn.searches:
                    lines.append(
                        f"- User: '{turn.user_message}' → {search.function_name}('{search.search_query}') "
                        f"→ {search.result_count} results"
                    )

        return "\n".join(lines)
