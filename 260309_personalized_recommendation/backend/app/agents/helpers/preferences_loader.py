import logging
from typing import Dict, List, Optional

from ..services.azure_ai_search_service import AzureAiSearchSingleton
from ..settings.azure_ai_search_settings import AzureSearchSettings
from ..models.const import PreferencesType
from ..models.agent_models import UserPreferences

logger = logging.getLogger(__name__)


class PreferencesLoader:
    """
    Loads user preferences from Azure AI Search index.

    Index: customer-preferences-index (from AzureSearchSettings)
    Fields: CustomerId, FinalSummary, PreferenceType, Category, FinalSummaryVector
    """

    def __init__(self):
        self._settings = AzureSearchSettings()
        self._index_name = self._settings.index_name_preferences
        self._search_client = AzureAiSearchSingleton.get_client(self._index_name)

        self._cache: Dict[str, UserPreferences] = {}

    def _query_preference(
        self,
        user_id: str,
        pref_type: PreferencesType,
        category: Optional[str] = None,
    ) -> Optional[dict]:
        filter_clauses = [f"CustomerId eq '{user_id}'"]

        if not pref_type:
            raise ValueError("pref_type must be provided")

        filter_clauses.append(f"PreferenceType eq '{pref_type.value}'")

        if pref_type == PreferencesType.CATEGORY:
            if not category:
                raise ValueError("category must be provided for category preferences")
            filter_clauses.append(f"Category eq '{category}'")

        odata_filter = " and ".join(filter_clauses)

        try:
            results = self._search_client.search(
                search_text="*",
                filter=odata_filter,
                select=self._settings.select_fields_customer_preferences,
                top=1,
            )
            for doc in results:
                return dict(doc)
            return None
        except Exception as e:
            logger.error(f"Error querying preferences for {user_id}: {e}")
            return None

    def load_user_preferences(self, user_id: str) -> UserPreferences:
        """
        Load all preferences for a user when they are recognized.
        """
        if user_id in self._cache:
            logger.debug(f"Using cached preferences for {user_id}")
            return self._cache[user_id]

        overall_doc = self._query_preference(user_id, PreferencesType.OVERALL)
        short_term_doc = self._query_preference(user_id, PreferencesType.SHORT_TERM)

        overall_summary = overall_doc.get("FinalSummary", "") if overall_doc else ""
        short_term_summary = (
            short_term_doc.get("FinalSummary", "") if short_term_doc else ""
        )

        preferences = UserPreferences(
            user_id=user_id,
            overall_summary=overall_summary,
            short_term_summary=short_term_summary,
            is_loaded=True,
        )

        self._cache[user_id] = preferences
        logger.info(f"Loaded preferences for user {user_id}")
        return preferences

    def get_category_preference(self, user_id: str, category: str) -> Optional[str]:
        """Load category-specific preferences for a user."""
        if user_id in self._cache:
            cached = self._cache[user_id].category_summaries.get(category)
            if cached:
                return cached

        doc = self._query_preference(
            user_id, pref_type=PreferencesType.CATEGORY, category=category
        )

        if not doc:
            return None

        summary = doc.get("FinalSummary", "")

        if summary and user_id in self._cache:
            self._cache[user_id].category_summaries[category] = summary

        return summary

    def list_available_users(self) -> List[str]:
        """List all users who have preferences in the index."""
        try:
            results = self._search_client.search(
                search_text="*",
                select=["CustomerId"],
                facets=["CustomerId"],
            )
            facets = results.get_facets()
            if facets and "CustomerId" in facets:
                return [f["value"] for f in facets["CustomerId"]]
            return []
        except Exception as e:
            logger.error(f"Error listing available users: {e}")
            return []

    def clear_cache(self):
        self._cache.clear()
        logger.debug("Preferences cache cleared")
