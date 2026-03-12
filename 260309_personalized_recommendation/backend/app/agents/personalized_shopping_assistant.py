"""
Personalized Search Agent (Semantic Kernel ChatCompletionAgent)

A personalized product search agent built on SK's ChatCompletionAgent.

Usage:
    # When user logs in
    agent = PersonalizedShoppingAssistant(user_id="customer_001")

    # Chat with the agent
    response = await agent.chat("I'm looking for a summer dress")

    # Follow-up (history maintained)
    response = await agent.chat("Do you have it in blue?")

    # Stream responses
    async for chunk in agent.chat_stream("Show me accessories"):
        print(chunk, end="")

    # Cleanup
    await agent.close()
"""

import logging
from typing import Optional, AsyncIterable

from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent, ChatHistoryAgentThread
from semantic_kernel.filters import FunctionInvocationContext

from .models.agent_models import UserPreferences
from .models.search import SearchResponse
from .models.search_memory import SearchMemory
from .helpers.preferences_loader import PreferencesLoader
from .helpers.setup_kernel import setup_kernel
from .plugins.search_plugin import SearchPlugin
from .services.azure_ai_search_service import AzureAiSearchSingleton

logger = logging.getLogger(__name__)

SEARCH_PLUGIN_FUNCTIONS = {
    "search_products",
    "get_product_by_id",
    "more_like_this",
    "item_detection",
}


BASE_SYSTEM_PROMPT = """You are a friendly and helpful personal shopping assistant for an online fashion retailer.

Your capabilities:
- Perform item detection using the item_detection function
- Search for products using the search_products function
- Find similar items using more_like_this function
- Get specific product details using get_product_by_id function

IMPORTANT – Product references:
- Each search result has a 1-based "position" field. "first item" = position 1, "second item" = position 2, etc.
- When calling get_product_by_id or more_like_this, use the product_id (Id) from the search result – e.g. "466595024". NEVER use the position number as product_id.

Guidelines:
- Always search for products when the user asks about items, styles, or makes shopping requests
- Be conversational and helpful
- When showing results, highlight key features like color, style, and material
- If no results found, suggest alternative searches or ask clarifying questions
- Remember context from the conversation for follow-up queries
"""

PERSONALIZED_SYSTEM_PROMPT = """
You are a friendly and helpful personal shopping assistant for an online fashion retailer.
You have access to the customer's preferences and recent activity to personalize your recommendations and you will adapt your responses based on their 
preferences and personality.
Your goal is to find and recommend products that match the customer's preferences, providing a fully personalized shopping experience.
If a customer is new, you will not be provided with any preferences, and you will act as a general shopping assistant.

## General Rules
- You don't provide answers to questions about topics outside of shopping and fashion.
- Outside of shopping and fashion, you can only engage in chit-chat conversations to questions like "hi", "how are you?" or "what can you do?", or asking clarification questions if the user query isn't comprehensible.
- You always accomplish tasks using the provided tools and functions, you never use your own knowledge in these cases.

## Preferences Types
- You can be equipped with 3 different types of preferences:
    1) Overall Preferences: These are long-term preferences that reflect the customer's general cross-category taste. They are typically (but not limited to) related to fit and comfort, quality, material, style, color. They are the most important ones and, unless irrelevant, they should always be included in the search query.
    2) Short-term Preferences: These are recent preferences based on the customer's latest interactions and activities on the platform. They share some characteristics with overall preferences but they are lower-level oriented towards the last items or categories the user has interacted with. To be used ONLY IF they add value with respect to the overall preferences 
    3) Category Preferences: These are specific preferences related to particular product categories (e.g., "Garment Upper Body", "Garment Lower Body", "Accessories"). They provide more specific context on the user interests for a given category. They are dynamic and provided by the item detection step. If available, they concur with overall preferences to build a more complete context for category-specific searches.

## Product References (get_product_by_id, more_like_this)
- Each search result includes a 1-based "position" field. "first item" = position 1, "second item" = position 2, etc.
- ALWAYS use the product_id (Id) from search results when calling these functions. Example: if a result shows product_id='466595024', use "466595024".
- NEVER use the position number as product_id.

## Item Detection
- Extract the item (product) from the user query to be used for item detection. Examples:
    - "I am looking for a red dress" -> "red dress"
    - "I want to buy a pair of jeans because I am going on a city break and want a new outfit" -> "jeans"
- ALWAYS perform item detection as the FIRST step in the search process.
- Use the result to build a filter for the subsequent product search.

## Products Search Rules and Preferences Handling
- Combine the user query, chat history, and preferences to formulate one or more stand-alone search queries.
- Preferences should ALWAYS be included in the search query, unless the user explicitly looks for something that contradicts their preferences. Indeed, current query and chat history take precedence over preferences. e.g., if a user has an overall preference for "blue" as a color but requests "dark red" in the current query, the search query should consider "dark red", not "blue".
- Rephrase preferences focusing on keyword attributes that can be found in product descriptions. BE BRIEF. Few examples:
    - "the user value formal wear for everyday office use, with a tendency towards cotton fabrics and neutral colors" -> "formal wear, cotton fabric, neutral colors"
    - "the customer prefers casual and sporty styles, with a focus on comfort and breathable materials, with repeated purchases of blue items" -> "casual style, sporty style, comfort, breathable materials, blue color"
- UNACCEPTABLE search queries examples:
    - User query: "I want a t-shirt", Overall preferences: "prefer formal wear, cotton fabric", Search query: "t-shirt according to my preferences" (missing preferences)
    - User query: "Show me some ideas", Overall preferences: "prefer dark colors", Search query: "ideas according to my preferences" (missing preferences)
- Use the item detection result to filter your search.

## Customer Preferences

Here's what you know about their preferences:

### Overall Preferences
{overall_preferences}

### Short-term Preferences
{short_term_preferences}

"""


class PersonalizedShoppingAssistant:
    """
    Personalized Shopping agent built on Semantic Kernel's ChatCompletionAgent.
    """

    def __init__(
        self,
        user_id: Optional[str] = None,
    ):
        self.user_id = user_id
        self.preferences: Optional[UserPreferences] = None
        self.thread = ChatHistoryAgentThread()

        self.search_memory = SearchMemory(user_id=user_id)

        self._preferences_loader = PreferencesLoader()

        if user_id:
            self._load_preferences(user_id)

        self.system_prompt = self._build_system_prompt()
        self._kernel = self._create_kernel()

        self.agent = ChatCompletionAgent(
            kernel=self._kernel,
            name="PersonalizedShoppingAssistant",
            instructions=self.system_prompt,
        )

        logger.info(
            f"PersonalizedShoppingAssistant initialized for user: {user_id or 'anonymous'}"
        )

    @classmethod
    def create(cls, user_id: Optional[str] = None) -> "PersonalizedShoppingAssistant":
        return cls(user_id=user_id)

    def _load_preferences(self, user_id: str) -> None:
        try:
            self.preferences = self._preferences_loader.load_user_preferences(user_id)
            logger.info(f"Loaded preferences for user {user_id}")
            logger.info(f"Overall prefs: {self.preferences.overall_summary}")
            logger.info(f"Short-term prefs: {self.preferences.short_term_summary}")
        except Exception as e:
            logger.warning(f"Failed to load preferences for {user_id}: {e}")
            self.preferences = None

    def _build_system_prompt(self) -> str:
        if self.preferences and self.preferences.is_loaded:
            return PERSONALIZED_SYSTEM_PROMPT.format(
                overall_preferences=self.preferences.overall_summary
                or "No overall preferences available.",
                short_term_preferences=self.preferences.short_term_summary
                or "No recent activity available.",
            )
        return BASE_SYSTEM_PROMPT

    def _create_kernel(self) -> Kernel:
        kernel = setup_kernel()

        search_plugin = SearchPlugin(
            user_id=self.user_id,
        )
        kernel.add_plugin(search_plugin, plugin_name="SearchPlugin")

        @kernel.filter(filter_type="function_invocation")
        async def record_search_filter(context: FunctionInvocationContext, next):
            await next(context)

            if (
                context.function.plugin_name == "SearchPlugin"
                and context.function.name in SEARCH_PLUGIN_FUNCTIONS
            ):
                result = context.result
                if result and isinstance(result.value, SearchResponse):
                    for i, r in enumerate(result.value.results):
                        r.position = i + 1

                    args = context.arguments
                    query = args.get("query") or args.get("product_id") or ""

                    self.search_memory.record_search(
                        search_query=str(query),
                        function_name=context.function.name,
                        function_arguments=dict(args),
                        results=result.value,
                    )

        logger.debug("SearchPlugin registered with kernel and search filter")
        return kernel

    async def chat(self, message: str) -> str:
        self.search_memory.start_turn(user_message=message)

        try:
            response = await self.agent.get_response(
                messages=message, thread=self.thread
            )
            return str(response.message.content)
        finally:
            self.search_memory.end_turn()

    async def chat_stream(self, message: str) -> AsyncIterable[str]:
        self.search_memory.start_turn(user_message=message)

        try:
            async for response in self.agent.invoke_stream(
                messages=message, thread=self.thread
            ):
                if hasattr(response, "message") and response.message:
                    yield str(response.message.content)
        finally:
            self.search_memory.end_turn()

    def get_category_preference(self, category: str) -> Optional[str]:
        if not self.user_id:
            return None
        return self._preferences_loader.get_category_preference(self.user_id, category)

    def clear_history(self) -> None:
        self.thread = ChatHistoryAgentThread()
        logger.debug("Conversation thread cleared")

    def clear_search_memory(self) -> None:
        self.search_memory = SearchMemory(user_id=self.user_id)

        self._kernel = self._create_kernel()
        self.agent = ChatCompletionAgent(
            kernel=self._kernel,
            name="PersonalizedSearchAgent",
            instructions=self.system_prompt,
        )
        logger.debug("Search memory cleared and plugin recreated")

    def get_session_info(self) -> dict:
        return {
            "user_id": self.user_id,
            "is_personalized": self.preferences is not None
            and self.preferences.is_loaded,
            "has_overall_prefs": bool(
                self.preferences and self.preferences.overall_summary
            ),
            "has_short_term_prefs": bool(
                self.preferences and self.preferences.short_term_summary
            ),
            "rs_reranking_enabled": self.user_id is not None,
            "search_memory": {
                "session_id": self.search_memory.session_id,
                "total_turns": len(self.search_memory.turns),
                "total_searches": self.search_memory.total_searches,
            },
        }

    def get_search_history(self) -> list:
        return self.search_memory.get_search_history()

    def get_last_turn_searches(self) -> Optional[dict]:
        last_turn = self.search_memory.last_turn
        if not last_turn:
            return None

        all_results = last_turn.get_all_results()

        return {
            "user_message": last_turn.user_message,
            "search_count": last_turn.search_count,
            "total_results": last_turn.total_results,
            "searches": [
                {
                    "function": s.function_name,
                    "query": s.search_query,
                    "result_count": s.result_count,
                    "is_reranked": s.results.is_reranked if s.results else False,
                    "reranking_model": s.results.reranking_model if s.results else None,
                }
                for s in last_turn.searches
            ],
            "results": [
                {
                    "article_id": r.article_id,
                    "search_score": r.effective_search_score,
                    "rs_score": r.rs_score,
                    "rs_model": r.rs_model,
                    "final_score": r.final_score,
                    "original_rank": r.search_rank,
                    "final_rank": r.final_rank,
                    "document": r.document,
                }
                for r in all_results
            ],
        }

    def get_last_turn_ranked_results(self) -> Optional[list]:
        last_turn = self.search_memory.last_turn
        if not last_turn:
            return None
        return last_turn.get_all_results()

    async def close(self) -> None:
        await AzureAiSearchSingleton.close_all()
        logger.info("PersonalizedSearchAgent closed")
