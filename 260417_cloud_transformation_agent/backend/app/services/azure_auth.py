"""Azure credential management for Phase 0."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.identity import ClientSecretCredential, DefaultAzureCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.subscription import SubscriptionClient


def build_credential(
    method: str,
    tenant_id: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
):
    """Return an Azure credential object. Never stored — caller owns the lifetime."""
    if method == "service_principal":
        missing = [f for f, v in [("tenant_id", tenant_id), ("client_id", client_id), ("client_secret", client_secret)] if not v]
        if missing:
            raise ValueError(f"service_principal requires: {', '.join(missing)}")
        return ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
    # "cli" — DefaultAzureCredential walks: env vars → workload identity → managed identity → az login
    return DefaultAzureCredential()


def list_subscriptions(credential) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """Return (subscriptions, error_message)."""
    try:
        client = SubscriptionClient(credential)
        subs = []
        for s in client.subscriptions.list():
            state = s.state.value if hasattr(s.state, "value") else str(s.state)
            tenant_id = getattr(s, "tenant_id", None) or ""
            subs.append({
                "subscription_id": s.subscription_id,
                "display_name": s.display_name,
                "state": state,
                "tenant_id": tenant_id,
            })
        if not subs:
            return [], "No subscriptions found for this credential. Check tenant and RBAC assignments."
        return subs, None
    except ClientAuthenticationError as e:
        msg = str(e.message or e)
        if "az login" in msg.lower() or "please run" in msg.lower():
            return [], "Azure CLI not logged in. Run `az login` first, or use Service Principal."
        return [], f"Authentication failed: {msg[:300]}"
    except Exception as e:
        return [], str(e)[:300]


def verify_subscription(credential, subscription_id: str) -> Dict[str, Any]:
    """Quick read-access probe on the target subscription."""
    try:
        rg_client = ResourceManagementClient(credential, subscription_id)
        # list_by_resource_group requires a name; list() is enough
        next(iter(rg_client.resource_groups.list()), None)
        return {"accessible": True}
    except HttpResponseError as e:
        code = getattr(e, "error", None)
        code_str = code.code if code else str(e.status_code)
        if code_str in ("AuthorizationFailed", "403"):
            return {"accessible": False, "reason": "Insufficient permissions. Need at least Reader role on this subscription."}
        return {"accessible": False, "reason": str(e)[:200]}
    except Exception as e:
        return {"accessible": False, "reason": str(e)[:200]}
