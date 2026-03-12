# Personalized Shopping Assistant Agent

A personalized product search agent built on Semantic Kernel's ChatCompletionAgent.

## Features

- **Personalized Search**: Uses Azure AI Search with hybrid semantic + vector search
- **User Preferences**: Loads and applies user preferences for personalized recommendations
- **RS-based Reranking**: Recommender system scores are blended with search scores
- **Search Memory**: Tracks all search operations for attribution and analysis
- **Image Rendering**: Displays product images in Jupyter notebooks

## Directory Structure

```
agents/
├── __init__.py
├── personalized_shopping_assistant.py  # Main agent class
├── requirements.txt
├── README.md
├── .env.example
├── models/
│   ├── __init__.py
│   ├── const.py              # Enums (PreferencesType, RankingModel, etc.)
│   ├── agent_models.py       # UserPreferences, SearchQuery, ProductResult
│   ├── search.py             # SearchResult, SearchResponse
│   └── search_memory.py      # SearchMemory, SearchRecord
├── settings/
│   ├── __init__.py
│   ├── application_settings.py
│   ├── azure_ai_search_settings.py
│   ├── azure_open_ai_settings.py
│   ├── azure_storage_settings.py
│   ├── data_settings.py
│   └── ranking_settings.py
├── services/
│   ├── __init__.py
│   ├── azure_ai_search_service.py
│   ├── azure_openai_service.py
│   └── ranking_service.py
├── helpers/
│   ├── __init__.py
│   ├── ai_search_ops.py      # Azure Search operations
│   ├── preferences_loader.py # Load user preferences from index
│   ├── setup_kernel.py       # Semantic Kernel setup
│   └── image_renderer.py     # Product image display
└── plugins/
    ├── __init__.py
    └── search_plugin.py      # SK plugin for search functions
```

## Installation

```bash
pip install -r requirements.txt
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required environment variables:

```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-openai.openai.azure.com/
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_TEXT_EMBEDDING_DEPLOYMENT_NAME=text-embedding-ada-002
AZURE_OPENAI_API_KEY=your-api-key

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_API_KEY=your-search-key

# Azure Storage (for images)
AZURE_STORAGE_IMAGES_ACCOUNT_NAME=your-storage-account
AZURE_STORAGE_IMAGES_CONTAINER_NAME=hm-images
AZURE_STORAGE_IMAGES_SAS_TOKEN=your-sas-token

# Data paths (for recommender models)
DATA_RECOMMENDER_MODELS_PATH=/path/to/models
```

## Usage

### Basic Usage

```python
from agents import PersonalizedShoppingAssistant, ImageRenderer

# Create agent for a specific user
agent = PersonalizedShoppingAssistant(user_id="customer_001")

# Chat with the agent
response = await agent.chat("I'm looking for a summer dress")
print(response)

# Follow-up query (conversation context is maintained)
response = await agent.chat("Do you have it in blue?")
print(response)

# Display product images from last search
renderer = ImageRenderer()
results = agent.get_last_turn_ranked_results()
if results:
    renderer.display_products([r.document for r in results])

# Cleanup
await agent.close()
```

### Streaming Responses

```python
agent = PersonalizedShoppingAssistant(user_id="customer_001")

async for chunk in agent.chat_stream("Show me accessories"):
    print(chunk, end="")

await agent.close()
```

### Anonymous User (No Personalization)

```python
# Create agent without user_id for non-personalized search
agent = PersonalizedShoppingAssistant()
response = await agent.chat("Show me red dresses")
```

### Session Info and Search History

```python
# Get session information
info = agent.get_session_info()
print(f"User: {info['user_id']}")
print(f"Personalized: {info['is_personalized']}")

# Get search history
history = agent.get_search_history()
for turn in history:
    print(f"Query: {turn['user_message']}")
    for search in turn['searches']:
        print(f"  - {search['function']}: {search['result_count']} results")
```

### In Jupyter Notebook

```python
import sys
sys.path.append('..')  # Add parent directory to path

from agents import PersonalizedShoppingAssistant, ImageRenderer
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create agent
agent = PersonalizedShoppingAssistant(user_id="customer_001")

# Chat
response = await agent.chat("I need a new jacket for winter")
print(response)

# Display results
renderer = ImageRenderer()
results = agent.get_last_turn_ranked_results()
renderer.display_products(
    [r.document for r in results],
    columns=4,
    title="Search Results"
)
```

## Configuration

### Ranking Settings

```python
# Via environment variables
RANKING_SEARCH_WEIGHT=0.9
RANKING_RS_WEIGHT=0.1
RANKING_APPLY_RERANK=true
```

### Search Settings

```python
# Configure in azure_ai_search_settings.py or via env vars
AZURE_SEARCH_INDEX_NAME_ITEMS=articles-processed-index
AZURE_SEARCH_INDEX_NAME_PREFERENCES=customer-preferences-index
AZURE_SEARCH_FILTER_MISSING_IMAGES=true
```

## License

MIT
