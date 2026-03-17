"""
Orchestration Agent
===================
Azure OpenAI agent with tool use for healthcare supply chain advisory.
Adapted for backend service usage (no terminal UI).
"""

import os
import json
from typing import Optional
from dotenv import load_dotenv

from . import data_loader
from .similarity_model import get_model, SimilarityAlgorithm, ModelConfig

load_dotenv()

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_summary_stats",
            "description": "Get aggregate statistics about customers and products. ALWAYS call this FIRST when asked about 'biggest', 'largest', 'top', 'average', or comparative questions.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_profile",
            "description": "Get detailed profile for a specific customer including purchasing patterns and active product categories",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The customer ID (e.g., CG-001)",
                    }
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_similar_customers",
            "description": "Find customers with similar purchasing behavior using Jaccard similarity on category purchase patterns",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The customer ID to find similar customers for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of similar customers to return",
                        "default": 5,
                    },
                    "min_similarity": {
                        "type": "number",
                        "description": "Minimum similarity score (0-1)",
                        "default": 0.5,
                    },
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_recommendations",
            "description": "Get product recommendations for a customer based on what similar customers purchase",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The customer ID to get recommendations for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of recommendations",
                        "default": 10,
                    },
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_inventory_alerts",
            "description": "Check for any active inventory alerts or shortages across regions",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_regional_inventory",
            "description": "Get inventory status for a specific region",
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "string",
                        "description": "Region name (midwest, northeast, southeast, southwest, west)",
                    }
                },
                "required": ["region"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_customers",
            "description": "List customers with optional filtering by region or type. Use sort_by='-total_orders_90d' or sort_by='-avg_order_value' for descending order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {"type": "string", "description": "Filter by region"},
                    "type": {"type": "string", "description": "Filter by facility type"},
                    "sort_by": {
                        "type": "string",
                        "description": "Sort field. Prefix '-' for descending. Options: total_orders_90d, avg_order_value, name",
                    },
                    "limit": {"type": "integer", "description": "Max results", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_model_summary",
            "description": "Get the ML model's current status, configuration, and key metrics.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_similarity",
            "description": "Explain WHY two customers are similar with a detailed breakdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_a": {"type": "string", "description": "First customer ID"},
                    "customer_b": {"type": "string", "description": "Second customer ID"},
                },
                "required": ["customer_a", "customer_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_feature_importance",
            "description": "Get which product categories are most important for determining customer similarity.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_algorithms",
            "description": "Compare how different similarity algorithms rank neighbors for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "Customer ID to compare"}
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrain_model",
            "description": "Retrain the similarity model with new parameters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "algorithm": {
                        "type": "string",
                        "description": "Similarity algorithm",
                        "enum": ["jaccard", "cosine", "dice", "overlap"],
                    },
                    "min_similarity_threshold": {
                        "type": "number",
                        "description": "Minimum similarity threshold (0.0-1.0)",
                        "default": 0.3,
                    },
                    "use_behavioral_weights": {
                        "type": "boolean",
                        "description": "Weight categories by behavioral vectors",
                        "default": False,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_algorithms",
            "description": "List all available similarity algorithms with formulas and use cases.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

SYSTEM_PROMPT = """You are a healthcare supply chain advisor with DATA SCIENTIST capabilities. Help users with customer profiling, product recommendations, inventory optimization, AND understanding the ML model.

CRITICAL GUARDRAILS:
1. ALWAYS call tools BEFORE making any claims about data. Never fabricate or assume data.
2. Express uncertainty if you haven't retrieved data.
3. DO NOT give investment or financial advice.
4. CITE specific data points from tool results.
5. If you cannot retrieve relevant data, acknowledge this limitation.
6. SUPERLATIVES REQUIRE VERIFICATION: For "biggest", "largest", "top", etc., call get_summary_stats FIRST.

ML MODEL INTERACTION:
You can interact with the ML model like a data scientist:
- get_model_summary: See current algorithm, parameters, training metrics
- explain_similarity: Understand WHY two customers are similar
- get_feature_importance: Which categories drive similarity most
- compare_algorithms: Compare Jaccard vs Cosine vs Dice vs Overlap
- retrain_model: Change algorithm or parameters
- list_algorithms: Get formulas and use cases

Guidelines:
- Be thorough but organized
- Use bullet points or numbered lists for clarity
- Include relevant metrics
- Highlight actionable insights
- Always ground responses in retrieved data
- When explaining similarity, show shared categories and formula used"""


class OrchestrationAgent:
    def __init__(self):
        from openai import AzureOpenAI

        if not AZURE_OPENAI_ENDPOINT:
            raise ValueError("Azure OpenAI credentials not configured. Set AZURE_OPENAI_ENDPOINT.")

        if AZURE_OPENAI_API_KEY:
            self.client = AzureOpenAI(
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_key=AZURE_OPENAI_API_KEY,
                api_version=AZURE_OPENAI_API_VERSION,
            )
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            self.client = AzureOpenAI(
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                azure_ad_token_provider=token_provider,
                api_version=AZURE_OPENAI_API_VERSION,
            )

        self.conversation_history: list[dict] = []

    def _execute_tool(self, name: str, arguments: dict) -> str:
        try:
            if name == "get_summary_stats":
                result = data_loader.get_summary_stats()
            elif name == "get_customer_profile":
                result = data_loader.get_customer_profile(**arguments)
                if result is None:
                    result = {"error": f"Customer not found"}
            elif name == "find_similar_customers":
                result = data_loader.get_similar_customers(**arguments)
                if result is None:
                    result = {"error": f"Customer not found"}
            elif name == "get_product_recommendations":
                result = data_loader.get_product_recommendations(**arguments)
                if result is None:
                    result = {"error": f"Customer not found"}
            elif name == "check_inventory_alerts":
                result = data_loader.get_inventory_alerts()
            elif name == "get_regional_inventory":
                result = data_loader.get_regional_inventory(**arguments)
                if result is None:
                    result = {"error": f"Region not found"}
            elif name == "list_customers":
                result = data_loader.list_customers(**arguments)
            elif name == "get_model_summary":
                result = get_model().get_model_summary()
            elif name == "explain_similarity":
                result = get_model().explain_similarity(**arguments)
            elif name == "get_feature_importance":
                features = get_model().get_feature_importance()
                result = [
                    {
                        "rank": i + 1,
                        "category": f.category_name,
                        "frequency": f"{f.frequency:.1%}",
                        "discriminative_power": round(f.discriminative_power, 4),
                        "avg_similarity_contribution": round(f.avg_weight_in_similarities, 4),
                    }
                    for i, f in enumerate(features)
                ]
            elif name == "compare_algorithms":
                result = get_model().compare_algorithms(**arguments)
            elif name == "retrain_model":
                algo = arguments.get("algorithm", "jaccard")
                threshold = arguments.get("min_similarity_threshold", 0.3)
                weights = arguments.get("use_behavioral_weights", False)
                model = get_model()
                new_config = ModelConfig(
                    algorithm=SimilarityAlgorithm(algo),
                    min_similarity_threshold=threshold,
                    use_behavioral_weights=weights,
                )
                metrics = model.train(new_config)
                result = {
                    "status": "retrained",
                    "message": f"Model retrained with {algo} algorithm",
                    "training_metrics": metrics.to_dict(),
                    "new_config": new_config.to_dict(),
                }
            elif name == "list_algorithms":
                result = {
                    "algorithms": [
                        {"name": "jaccard", "formula": "|A ∩ B| / |A ∪ B|", "description": "Balanced measure of overlap."},
                        {"name": "cosine", "formula": "A·B / (||A|| × ||B||)", "description": "Measures angle between vectors."},
                        {"name": "dice", "formula": "2|A ∩ B| / (|A| + |B|)", "description": "Emphasizes overlap more."},
                        {"name": "overlap", "formula": "|A ∩ B| / min(|A|, |B|)", "description": "Ignores size differences."},
                    ],
                    "current": get_model().config.algorithm.value,
                }
            else:
                result = {"error": f"Unknown tool: {name}"}
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def chat(self, user_message: str) -> str:
        self.conversation_history.append({"role": "user", "content": user_message})

        MAX_HISTORY_MESSAGES = 8
        if len(self.conversation_history) > MAX_HISTORY_MESSAGES:
            self.conversation_history = self.conversation_history[-MAX_HISTORY_MESSAGES:]

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.conversation_history

        while True:
            response = self.client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=800,
                temperature=0.7,
            )

            assistant_message = response.choices[0].message

            if not assistant_message.tool_calls:
                response_content = assistant_message.content or ""
                self.conversation_history.append(
                    {"role": "assistant", "content": response_content}
                )
                return response_content

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in assistant_message.tool_calls
                    ],
                }
            )

            import concurrent.futures

            tool_calls_list = list(assistant_message.tool_calls)
            tool_results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(tool_calls_list)) as executor:
                future_to_tc = {
                    executor.submit(
                        self._execute_tool,
                        tc.function.name,
                        json.loads(tc.function.arguments),
                    ): tc
                    for tc in tool_calls_list
                }
                for future in concurrent.futures.as_completed(future_to_tc):
                    tc = future_to_tc[future]
                    try:
                        tool_results[tc.id] = future.result()
                    except Exception as e:
                        tool_results[tc.id] = json.dumps({"error": str(e)})

            for tool_call in tool_calls_list:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_results[tool_call.id],
                    }
                )

    def reset(self):
        self.conversation_history = []


_agents: dict[str, OrchestrationAgent] = {}


def get_agent(session_id: str) -> OrchestrationAgent:
    if session_id not in _agents:
        _agents[session_id] = OrchestrationAgent()
    return _agents[session_id]


def reset_agent(session_id: str):
    if session_id in _agents:
        _agents[session_id].reset()
