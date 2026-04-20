"""Migration planning agent: AWS resource scope → Azure migration plan (Azure OpenAI)."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider
from openai import AzureOpenAI

from .schema.migration_plan import MigrationPlan


def _plan_to_markdown(plan: MigrationPlan) -> str:
    lines: List[str] = [
        "## Summary",
        plan.summary.strip(),
        "",
        "## Assessment",
        plan.assessment.strip(),
        "",
        "## Migration steps",
    ]
    for i, step in enumerate(plan.steps, start=1):
        lines.append(f"### {i}. {step.phase}")
        lines.append(step.description.strip())
        if step.aws_components:
            lines.append(f"- **AWS:** {', '.join(step.aws_components)}")
        if step.azure_targets:
            lines.append(f"- **Azure:** {', '.join(step.azure_targets)}")
        if step.notes:
            lines.append(f"- *Notes:* {step.notes}")
        lines.append("")

    lines.append("## Risks")
    if not plan.risks:
        lines.append("_None called out._")
    else:
        for r in plan.risks:
            lines.append(f"- **{r.category}:** {r.detail}")
            if r.mitigation:
                lines.append(f"  - *Mitigation:* {r.mitigation}")

    lines.append("")
    lines.append("## Open questions")
    if not plan.open_questions:
        lines.append("_None._")
    else:
        for q in plan.open_questions:
            lines.append(f"- {q}")

    if plan.terraform:
        lines.append("")
        lines.append("## Azure Terraform module")
        lines.append(
            f"Generated {len(plan.terraform)} file(s). "
            "Run `terraform init && terraform plan && terraform apply` from the "
            "`terraform/` directory saved alongside this run."
        )
        for f in plan.terraform:
            lines.append("")
            lines.append(f"### `{f.filename}`")
            if f.description:
                lines.append(f"_{f.description}_")
            # Pick a reasonable fence language from the extension.
            lang = "hcl"
            lower = f.filename.lower()
            if lower.endswith(".md"):
                lang = "markdown"
            elif lower.endswith(".tfvars"):
                lang = "hcl"
            lines.append(f"```{lang}")
            lines.append(f.content.rstrip())
            lines.append("```")

    return "\n".join(lines).strip()


class MigrationAgent:
    """Azure OpenAI–backed planner for AWS → Azure migrations."""

    def __init__(
        self,
        *,
        llm_deployment: str,
        azure_openai_endpoint: str,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.llm_deployment = llm_deployment
        env_type = os.environ.get("ENVIRONMENT", "dev").lower()
        if env_type == "local":
            credential = DefaultAzureCredential()
        else:
            mid = os.environ.get("MANAGED_IDENTITY_CLIENT_ID")
            if not mid:
                raise ValueError(
                    "MANAGED_IDENTITY_CLIENT_ID is required when ENVIRONMENT is not local."
                )
            credential = ManagedIdentityCredential(client_id=mid)

        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        # Mirror the mapping agent: longer timeout + more retries to survive
        # occasional TLS resets on corp networks.
        self.client = AzureOpenAI(
            azure_endpoint=azure_openai_endpoint.rstrip("/"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            azure_ad_token_provider=token_provider,
            max_retries=int(os.getenv("AZURE_OPENAI_MAX_RETRIES", "5")),
            timeout=float(os.getenv("AZURE_OPENAI_TIMEOUT", "120")),
        )

        prompt_path = Path(__file__).resolve().parent / "prompts" / "migration_planner.yaml"
        with open(prompt_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._system_prompt = str(data.get("template", "")).strip()

    def run(
        self,
        *,
        aws_resource_spec: str,
        target_azure_region: str = "eastus",
        migration_goals: str = "",
        output_format: str = "json",
        azure_mappings: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        execution_log: List[str] = ["Migration planner: building request"]
        aws_scope = (aws_resource_spec or "").strip()
        if not aws_scope:
            return {
                "final_output": "Error: aws_resource_spec is empty.",
                "json_data": {"error": "aws_resource_spec is required"},
                "execution_log": execution_log + ["Aborted: empty scope"],
            }

        goals = (migration_goals or "").strip() or (
            "Standard lift-and-shift with security and operability best practices."
        )

        # When the UI has already run the mapping agent, the user saw and
        # implicitly approved those AWS→Azure target choices — treat them as
        # authoritative so the generated Terraform uses exactly the same
        # ``azurerm_*`` types shown on screen.
        mapping_block = ""
        if azure_mappings:
            mapping_block = (
                "\n\nAuthoritative AWS → Azure target mappings (already reviewed "
                "by the user — the Terraform module MUST use these exact "
                "`azurerm_*` resource types; do NOT substitute alternatives):\n"
                f"{json.dumps(azure_mappings, indent=2, default=str)}"
            )
            execution_log.append(
                f"Using {len(azure_mappings)} pre-computed Azure mapping(s)"
            )

        user_content = (
            f"AWS resources and scope:\n{aws_scope}\n\n"
            f"Target Azure region preference: {target_azure_region}\n"
            f"Migration goals and constraints: {goals}"
            f"{mapping_block}"
        )

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

        execution_log.append(
            "Invoking Azure OpenAI (structured migration plan + Terraform module)"
        )
        try:
            completion = self.client.beta.chat.completions.parse(
                model=self.llm_deployment,
                messages=messages,
                temperature=float(os.getenv("MIGRATION_AGENT_TEMPERATURE", "0.2")),
                #max_tokens=int(os.getenv("MIGRATION_AGENT_MAX_TOKENS", "8000")),
                response_format=MigrationPlan,
            )
            msg = completion.choices[0].message
            refusal = getattr(msg, "refusal", None)
            if refusal:
                raise RuntimeError(refusal)
            plan = msg.parsed
            if plan is None:
                raise RuntimeError("Model returned no parsed MigrationPlan")
        except Exception as e:
            self.logger.exception("Migration planner invocation failed")
            execution_log.append(f"Error: {e}")
            return {
                "final_output": f"Migration planning failed: {e}",
                "json_data": {"error": str(e)},
                "execution_log": execution_log,
            }

        tf_count = len(plan.terraform or [])
        execution_log.append(
            f"Received structured MigrationPlan (terraform files: {tf_count})"
        )

        if str(output_format).lower() == "plain_text":
            narrative = self.client.chat.completions.create(
                model=self.llm_deployment,
                temperature=0.2,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Summarize this migration plan in clear prose for stakeholders. "
                            "Do not add new technical claims.\n\n"
                            f"{json.dumps(plan.model_dump(), indent=2)}"
                        ),
                    },
                ],
            )
            final_text = narrative.choices[0].message.content or ""
            return {
                "final_output": final_text.strip(),
                "json_data": plan.model_dump(),
                "execution_log": execution_log + ["Generated plain-text summary"],
            }

        md = _plan_to_markdown(plan)
        return {
            "final_output": md,
            "json_data": plan.model_dump(),
            "execution_log": execution_log + ["Rendered markdown from structured plan"],
        }
