"""Structured output for AWS → Azure migration planning."""

from pydantic import BaseModel, Field


class MigrationStep(BaseModel):
    phase: str = Field(description="Short phase name, e.g. Discover, Design, Migrate, Validate")
    description: str = Field(description="What to do in this phase")
    aws_components: list[str] = Field(default_factory=list, description="Relevant AWS services or patterns")
    azure_targets: list[str] = Field(default_factory=list, description="Suggested Azure services or landing zones")
    notes: str = Field(default="", description="Dependencies, tooling, or sequencing notes")


class MigrationRisk(BaseModel):
    category: str = Field(description="e.g. Data, Security, Networking, Operations")
    detail: str = Field(description="Risk description")
    mitigation: str = Field(default="", description="How to reduce or accept the risk")


class TerraformFile(BaseModel):
    """A single file in a ready-to-deploy Azure Terraform module."""

    filename: str = Field(
        description=(
            "Relative path inside the terraform module, e.g. 'main.tf', "
            "'variables.tf', 'outputs.tf', 'providers.tf', 'README.md'. "
            "Must end with .tf, .tfvars, .md, or .hcl."
        )
    )
    content: str = Field(
        description=(
            "Full file content. For .tf files, must be valid HCL that passes "
            "`terraform init && terraform validate`. Do not include Markdown "
            "fences or commentary outside the file."
        )
    )
    description: str = Field(
        default="", description="One-sentence description of what this file is for."
    )


class MigrationPlan(BaseModel):
    summary: str = Field(description="Executive summary of the migration approach")
    assessment: str = Field(
        description="Brief assessment of complexity, dependencies, and prerequisites"
    )
    steps: list[MigrationStep] = Field(default_factory=list, description="Ordered migration steps")
    risks: list[MigrationRisk] = Field(default_factory=list, description="Key risks and mitigations")
    open_questions: list[str] = Field(
        default_factory=list,
        description="Decisions or missing information needed before execution",
    )
    terraform: list[TerraformFile] = Field(
        default_factory=list,
        description=(
            "Complete, deployable Azure Terraform module implementing the plan. "
            "MUST include at minimum providers.tf, variables.tf, main.tf, "
            "outputs.tf, and README.md. Use the azurerm provider."
        ),
    )
