import logging
from typing import Dict

from fastapi import APIRouter

from .. import schemas
from ..agents import PersonalizedShoppingAssistant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chats", tags=["chats"])

DEFAULT_USER_ID = "f5f307139b407340dca5d0c9fa34b97514b730cc6399e49457b051556904ff0f"

# Keep agent instances alive per customer to preserve chat history
_agent_cache: Dict[str, PersonalizedShoppingAssistant] = {}


def _get_or_create_agent(user_id: str) -> PersonalizedShoppingAssistant:
    if user_id not in _agent_cache:
        logger.info(f"Creating new agent for user {user_id[:12]}…")
        _agent_cache[user_id] = PersonalizedShoppingAssistant(user_id=user_id)
    return _agent_cache[user_id]


def _search_result_to_chat_item(result):
    """Convert SearchResult to ChatSearchResult with image_url."""
    doc = result.document if hasattr(result, "document") else {}
    raw_id = doc.get("Id")
    if raw_id is None:
        return None
    article_id = str(raw_id).zfill(10)
    prefix = article_id[:3] if len(article_id) >= 3 else "000"
    image_url = f"/images/{prefix}/{article_id}.jpg"
    return schemas.ChatSearchResult(
        article_id=str(raw_id),
        prod_name=doc.get("ProductName"),
        product_type_name=doc.get("ProductTypeName"),
        colour_group_name=doc.get("ColourGroupName"),
        image_url=image_url,
        rs_model=getattr(result, "rs_model", None),
        rs_score=getattr(result, "rs_score", None),
        search_rank=getattr(result, "search_rank", None),
        rs_rank=getattr(result, "rs_rank", None),
        final_rank=getattr(result, "final_rank", None),
    )


@router.post("", response_model=schemas.ChatResponse)
async def send_message(body: schemas.ChatMessage):
    """Receive a user prompt and return an AI agent reply with search results (images)."""

    user_id = body.customer_id or DEFAULT_USER_ID
    agent = _get_or_create_agent(user_id)
    reply = await agent.chat(body.message)

    search_results = None
    search_info = None
    last_turn = agent.search_memory.last_turn
    if last_turn and not last_turn.was_clarification_only:
        results = last_turn.get_all_results_deduplicated()
        if results:
            items = []
            for r in results:
                item = _search_result_to_chat_item(r)
                if item is not None:
                    items.append(item)
            search_results = items if items else None

        if last_turn.searches:
            search_info = []
            for s in last_turn.searches:
                args = s.function_arguments or {}
                search_info.append(
                    schemas.ChatSearchInfo(
                        function=s.function_name,
                        enriched_query=args.get("query"),
                        item_detection_filter=args.get("item_detection_filter"),
                        use_rs_candidate_filter=args.get("use_rs_candidate_filter"),
                        result_count=s.result_count,
                    )
                )

    return schemas.ChatResponse(
        reply=reply, search_results=search_results, search_info=search_info
    )


@router.delete("")
async def reset_chat(customer_id: str = None):
    """Reset chat history for a customer (or all if no customer_id)."""
    if customer_id:
        if customer_id in _agent_cache:
            del _agent_cache[customer_id]
            return {"status": "ok", "message": f"Chat reset for {customer_id[:12]}…"}
        return {"status": "ok", "message": "No active session"}
    _agent_cache.clear()
    return {"status": "ok", "message": "All chat sessions reset"}
