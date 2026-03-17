from typing import Annotated, Dict, List, Optional, TypedDict
from langgraph.graph.message import AnyMessage, add_messages


class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    execution_log: List[str]
    search_results: str
    dataframe_context: str
    final_output: str
    tool_retry_count: int
    json_data: Optional[Dict[str, object]]
