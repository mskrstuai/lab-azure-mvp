"""Analytics Agent - migrated from agentic-analytics."""

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd
import requests
import yaml
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobClient
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from requests.auth import HTTPBasicAuth

from .schema.promo_generator.portfolio_output import PortfolioOutput
from .state import AgentState


@dataclass
class AzureSearchConfig:
    endpoint: str
    key: str
    index: str
    semantic_configuration_name: str = "default-semantic-config"
    k_nearest_neighbors: int = 5


class AnalyticsAgent:
    """Run LangGraph-based analytics with pandas DataFrames."""

    @staticmethod
    def _escape_prompt_value(value: str) -> str:
        """Escape curly braces to avoid ChatPromptTemplate KeyError."""
        return value.replace("{", "{{").replace("}", "}}")

    def __init__(
        self,
        *,
        dataset_path: str,
        llm_deployment: str,
        azure_openai_endpoint: str,
        embedding_deployment: str,
        persona: str = "promo_generator",
        azure_search_config: Optional[AzureSearchConfig] = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.persona = persona
        self.dataset_path = str(dataset_path)
        self.logger.info(f" |- Initializing AnalyticsAgent with dataset_path: {self.dataset_path}")
        self.logger.info(f" |- Persona set to: {self.persona}")

        local_csv_path = self._resolve_dataset_path(self.dataset_path)
        self.logger.info(f" |- Loading dataset from {local_csv_path}")
        self.input_df = pd.read_csv(local_csv_path)

        env_type = os.environ.get("ENVIRONMENT", "dev").lower()
        if env_type == "local":
            self._credential = DefaultAzureCredential()
        else:
            managed_identity_client_id = os.environ.get("MANAGED_IDENTITY_CLIENT_ID")
            if not managed_identity_client_id:
                raise ValueError(
                    "MANAGED_IDENTITY_CLIENT_ID environment variable is required for non-local environments."
                )
            self._credential = ManagedIdentityCredential(client_id=managed_identity_client_id)
        self._token_scope = "https://cognitiveservices.azure.com/.default"

        def _token_provider() -> str:
            token = self._credential.get_token(self._token_scope)
            return token.token

        self._token_provider = _token_provider

        self.llm = AzureChatOpenAI(
            azure_deployment=llm_deployment,
            azure_endpoint=azure_openai_endpoint,
            api_version="2025-01-01-preview",
            temperature=1,
            azure_ad_token_provider=self._token_provider,
        )

        self.embedding = AzureOpenAIEmbeddings(
            azure_deployment=embedding_deployment,
            azure_endpoint=azure_openai_endpoint,
            api_version="2025-01-01-preview",
            azure_ad_token_provider=self._token_provider,
        )

        self.search_config = azure_search_config
        if azure_search_config and SearchClient and AzureKeyCredential:
            self.search_client = SearchClient(
                endpoint=azure_search_config.endpoint,
                index_name=azure_search_config.index,
                credential=AzureKeyCredential(azure_search_config.key),
            )
        else:
            self.search_client = None

    def _resolve_dataset_path(self, dataset_path: str) -> Path:
        env_type = os.environ.get("ENVIRONMENT", "dev").lower()

        if env_type == "local":
            local_path = Path(dataset_path).expanduser().resolve()
            if not local_path.exists():
                raise FileNotFoundError(f"Local dataset not found: {local_path}")
            return local_path

        storage_account_name = os.environ.get("STORAGE_ACCOUNT_NAME")
        if not storage_account_name:
            raise ValueError("STORAGE_ACCOUNT_NAME environment variable is not set.")

        account_url = f"https://{storage_account_name}.blob.core.windows.net"
        parsed = urlparse(dataset_path)
        if parsed.scheme and parsed.netloc:
            path_parts = parsed.path.split("/")
            if len(path_parts) < 3:
                raise ValueError("Blob URL path must include '/<container>/<blob>'")
            container_name = path_parts[1]
            blob_name = "/".join(path_parts[2:])
        else:
            path = str(dataset_path).lstrip("/")
            parts = path.split("/")
            if len(parts) < 2:
                raise ValueError("dataset_path must be '/<container>/<blob>' or a full https URL")
            container_name = parts[0]
            blob_name = "/".join(parts[1:])

        downloads_dir = Path("data") / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(blob_name).name or f"dataset_{uuid.uuid4().hex}.csv"
        target_path = downloads_dir / filename

        if env_type == "local":
            credential = DefaultAzureCredential()
        else:
            managed_identity_client_id = os.environ.get("MANAGED_IDENTITY_CLIENT_ID")
            if not managed_identity_client_id:
                raise ValueError(
                    "MANAGED_IDENTITY_CLIENT_ID environment variable is required for non-local environments."
                )
            credential = ManagedIdentityCredential(client_id=managed_identity_client_id)

        blob_client = BlobClient(
            account_url=account_url,
            container_name=container_name,
            blob_name=blob_name,
            credential=credential,
        )
        if not blob_client.exists():
            raise FileNotFoundError(f"Dataset not found at {dataset_path}")
        with open(target_path, "wb") as fh:
            fh.write(blob_client.download_blob().readall())
        return target_path

    def run(
        self,
        instruction: str,
        enable_search: bool = False,
        search_query: Optional[str] = None,
        output_format: Optional[str] = None,
    ) -> Dict[str, object]:
        if enable_search and not self.search_client:
            raise RuntimeError("Azure Cognitive Search is not configured for this agent.")

        self.logger.info(f" |- Agent output format: {output_format or 'plain text'}")
        dataframe_context = self._build_dataframe_context()
        search_flag = enable_search and search_query not in (None, "")

        graph = self._setup_graph(
            instruction=instruction,
            dataframe_context=dataframe_context,
            enable_search=search_flag,
            search_query=search_query or instruction,
            output_format=output_format or "plain text",
        )

        initial_state: AgentState = {
            "messages": [HumanMessage(content=instruction)],
            "execution_log": [],
            "search_results": "",
            "dataframe_context": dataframe_context,
            "final_output": "",
            "tool_retry_count": 0,
        }

        self.logger.info(" |- Invoking agent workflow graph...")
        result = graph.invoke(
            initial_state, {"recursion_limit": int(os.getenv("RECURSION_LIMIT", 20))}
        )

        return {
            "execution_log": result.get("execution_log", []),
            "search_results": result.get("search_results", ""),
            "final_output": result.get("final_output", ""),
            "json_data": result.get("json_data", None),
        }

    def _setup_graph(
        self,
        *,
        instruction: str,
        dataframe_context: str,
        enable_search: bool,
        search_query: str,
        output_format: str,
    ):
        tools = [self._build_executor_tool()]

        def analyzer(state: AgentState) -> Dict[str, object]:
            messages = state.get("messages", [])
            tool_retry_count = state.get("tool_retry_count", 0)
            last_message = messages[-1] if messages else None
            failure_payload: Optional[str] = None

            if last_message is not None:
                last_msg_type = type(last_message).__name__
                last_message_content = (
                    getattr(last_message, "content", "")[:200]
                    if hasattr(last_message, "content")
                    else "No content"
                )

                if last_msg_type.lower() == "toolmessage":
                    if (
                        '"success": false' in last_message_content.lower()
                        and "code_execution_error" in last_message_content.lower()
                    ):
                        failure_payload = last_message_content

                    if failure_payload is not None:
                        if tool_retry_count < 5:
                            retry_feedback = f"""
                                Previous code execution failed with error:
                                {failure_payload}
                                Regenerate the code, ensuring valid python/pandas/numpy syntax and assigning final results in dict format to `output`.
                                Remember: `input_df` contains the available data for analysis. Do not assume any other variable or dataframe names.
                                Validate column names via `input_df.columns` and protect against divide-by-zero or missing values.
                                """
                            messages = messages + [HumanMessage(content=retry_feedback)]
                            state["messages"] = messages
                        else:
                            error_message = (
                                f"Execution failed after {tool_retry_count} retry attempts. "
                                f"Last error: {failure_payload[:500] if failure_payload else 'Unknown error'}"
                            )
                            return {
                                "messages": messages,
                                "execution_log": state.get("execution_log", [])
                                + [f"[Error] {error_message}"],
                                "final_output": f"Error: {error_message}",
                                "tool_retry_count": tool_retry_count,
                            }
                    else:
                        state["tool_retry_count"] = 0
                        tool_output = getattr(last_message, "content", "")
                        if tool_output:
                            current_log = state.get("execution_log", [])
                            tool_index = (
                                len([log for log in current_log if log.startswith("[Tool Output")])
                                + 1
                            )
                            formatted_output = (
                                json.dumps(json.loads(tool_output), indent=2)
                                if tool_output.startswith("{")
                                else tool_output
                            )
                            state["execution_log"] = current_log + [
                                f"[Tool Output #{tool_index}]\n{formatted_output}"
                            ]

            search_context = state.get("search_results", "")
            system_prompt = self._build_analyzer_system_prompt(
                dataframe_context=dataframe_context,
                search_results=search_context,
            )
            prior_outputs = "\n---\n".join(state.get("execution_log", []))

            assistant_prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", system_prompt),
                    ("placeholder", "{messages}"),
                    (
                        "human",
                        """Process the user's instruction.

                            Instruction: {instruction}
                            Execution logs (Reuse computation results when relevant):
                            {prior_outputs}

                            Use the python tool when computation is required. Once computations are completed, synthesize the entire analysis into a final response in required format.
                            Respond with analysis, calculations, and cite any tool outputs.
                            """,
                    ),
                ]
            ).partial(
                instruction=self._escape_prompt_value(instruction),
                prior_outputs=self._escape_prompt_value(
                    prior_outputs or "No computations available yet."
                ),
            )

            llm_with_tools = assistant_prompt | self.llm.bind_tools(tools)
            response = llm_with_tools.invoke(state)

            execution_log = state.get("execution_log", []) + [response.content]
            tool_calls = []
            if response is not None:
                extra = getattr(response, "additional_kwargs", {}) or {}
                tool_calls = getattr(response, "tool_calls", None) or extra.get(
                    "tool_calls", []
                )

            result = {
                "messages": messages + [response],
                "execution_log": execution_log,
                "tool_retry_count": 0,
            }
            if not tool_calls:
                result["final_output"] = response.content
            return result

        def to_json(state: AgentState) -> Dict[str, object]:
            final_output_text = state.get("final_output", "")
            if final_output_text.strip() == "":
                return {"json_data": {"error": "No final output text available for JSON conversion."}}
            try:
                json_llm = self.llm.with_structured_output(PortfolioOutput)
                parsed = json_llm.invoke(
                    (
                        "Convert the following output into the PortfolioOutput schema. "
                        "Prefer nulls/empty lists for missing fields; do not invent data.\n\n"
                        f"Output:\n{final_output_text}"
                    )
                )
                if hasattr(parsed, "model_dump"):
                    data = parsed.model_dump()
                else:
                    data = {"error": "Parsing to JSON data failed."}
                return {"json_data": data}
            except Exception as e:
                self.logger.error(f" |- JSON conversion failed: {e}")
                return {"json_data": {"error": str(e)}}

        def route_from_analyzer(state: AgentState) -> str:
            last_message = state.get("messages", [])[-1] if state.get("messages") else None
            tool_calls = []
            if last_message is not None:
                extra = getattr(last_message, "additional_kwargs", {}) or {}
                tool_calls = getattr(last_message, "tool_calls", None) or extra.get(
                    "tool_calls", []
                )
            if tool_calls:
                return "tools"
            if str(output_format).lower() == "json_converter":
                return "json_converter"
            return "done"

        workflow = StateGraph(AgentState)
        if enable_search:
            workflow.add_node(
                "search",
                lambda state: self._document_search(state, query=search_query),
            )
        workflow.add_node("analyzer", analyzer)
        workflow.add_node("tools", ToolNode(tools))

        if enable_search:
            workflow.add_edge(START, "search")
            workflow.add_edge("search", "analyzer")
        else:
            workflow.add_edge(START, "analyzer")

        if str(output_format).lower() == "json_converter":
            workflow.add_node("json_converter", to_json)
            workflow.add_conditional_edges(
                "analyzer",
                route_from_analyzer,
                {"tools": "tools", "json_converter": "json_converter", "done": END},
            )
            workflow.add_edge("json_converter", END)
        else:
            workflow.add_conditional_edges(
                "analyzer",
                route_from_analyzer,
                {"tools": "tools", "done": END},
            )
        workflow.add_edge("tools", "analyzer")
        return workflow.compile()

    def _build_executor_tool(self):
        executor_url = os.getenv("EXECUTOR_URL", "http://localhost:8000").rstrip("/")
        executor_username = os.getenv("EXECUTOR_USERNAME")
        executor_password = os.getenv("EXECUTOR_PASSWORD")

        @tool
        def python_executor(code: str) -> str:
            """Execute Python code remotely via the Executor API. The code must assign the final result to `output`."""
            payload = {
                "code": code,
                "dataset_uri": self.dataset_path,
                "timeout_sec": 120,
                "execution_id": str(uuid.uuid4()),
            }
            try:
                auth = (
                    HTTPBasicAuth(executor_username, executor_password)
                    if (executor_username and executor_password)
                    else None
                )
                resp = requests.post(
                    f"{executor_url}/execute",
                    json=payload,
                    timeout=120,
                    auth=auth,
                )
                if resp.status_code == 401:
                    return json.dumps(
                        {
                            "success": False,
                            "code_execution_error": "Unauthorized error from executor app.",
                        }
                    )
                resp.raise_for_status()
                return json.dumps(resp.json())
            except requests.RequestException as e:
                return json.dumps(
                    {"success": False, "code_execution_error": f"Executor request failed: {e}"}
                )
            except Exception as e:
                return json.dumps({"success": False, "code_execution_error": str(e)})

        return python_executor

    def _build_dataframe_context(self) -> str:
        df = self.input_df
        parts: List[str] = [f"Rows: {len(df):,}", f"Columns: {len(df.columns)}"]
        parts.append("Column dtypes:")
        for col, dtype in df.dtypes.items():
            parts.append(f"  - {col}: {dtype}")
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        if numeric_cols:
            stats = df[numeric_cols].describe().transpose().round(4)
            parts.append("Numeric describe (round 4dp):")
            parts.append(stats.to_csv())
        categorical_cols = df.select_dtypes(include="object").columns.tolist()
        for col in categorical_cols[:5]:
            top_values = df[col].value_counts().head(5)
            summary = ", ".join(f"{name} ({count})" for name, count in top_values.items())
            parts.append(f"Top {col}: {summary}")
        sample = df.head(3)
        parts.append("Sample rows:")
        parts.append(sample.to_csv(index=False))
        return "\n".join(parts)

    def _build_analyzer_system_prompt(
        self,
        *,
        dataframe_context: str,
        search_results: str,
    ) -> str:
        search_text = search_results or "No external market research applied."
        template = self._load_prompt_template("analyzer")
        environment_template = self._load_prompt_template("environment_info")
        environment_info = environment_template.format(
            dataframe_context=dataframe_context,
            search_results=search_text,
        )
        formatted = template.format(environment_info=environment_info)
        return self._escape_prompt_value(formatted)

    def _load_prompt_template(self, name: str) -> str:
        base_dir = Path(__file__).resolve().parent / "prompts"
        path = base_dir / self.persona / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict) or "template" not in data:
            raise ValueError(f"Invalid prompt YAML format in {path}: expected a 'template' key.")
        return str(data["template"]) or ""

    def _document_search(
        self,
        state: AgentState,
        *,
        query: str,
    ) -> Dict[str, object]:
        if not self.search_client:
            return {}
        query_embedding = self.embedding.embed_query(query)
        results = self.search_client.search(
            search_text=query,
            vector_queries=[
                {
                    "kind": "vector",
                    "vector": query_embedding,
                    "k_nearest_neighbors": self.search_config.k_nearest_neighbors,
                    "fields": "content_vector",
                }
            ],
            top=5,
            search_mode="any",
            query_type="semantic",
            semantic_configuration_name=self.search_config.semantic_configuration_name,
        )
        snippets: List[str] = []
        for idx, item in enumerate(results, start=1):
            source = item.get("file_name", "Unknown source")
            page = item.get("page_number", "?")
            score = item.get("@search.score", "?")
            content = item.get("content", "")
            snippets.append(f"[CIT{idx}] {source} (page {page}, score {score})\n{content}")
        return {"search_results": "\n\n".join(snippets)}
