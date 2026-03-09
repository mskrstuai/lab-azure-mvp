from fastapi import APIRouter

from .. import schemas

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", response_model=schemas.ChatResponse)
def send_message(body: schemas.ChatMessage):
    """Receive a user prompt and return an AI agent reply.

    This is a placeholder endpoint. Replace the static reply with a call
    to your AI agent / LLM service when ready.
    """
    return schemas.ChatResponse(
        reply=f"🤖 [Agent placeholder] Received your message: \"{body.message}\". "
        "Connect an AI agent here to generate real responses."
    )
