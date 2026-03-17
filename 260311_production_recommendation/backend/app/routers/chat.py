"""Chat API endpoint for the AI advisor agent."""

from fastapi import APIRouter
from pydantic import BaseModel

from ..orchestrator import get_agent, reset_agent

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@router.post("/chat")
async def chat(request: ChatRequest):
    agent = get_agent(request.session_id)
    reply = agent.chat(request.message)
    return ChatResponse(reply=reply, session_id=request.session_id)


@router.post("/chat/reset")
async def chat_reset(session_id: str = "default"):
    reset_agent(session_id)
    return {"status": "ok", "message": "Conversation reset"}
