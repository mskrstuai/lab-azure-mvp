"""V2 migration plan schemas — multi-module, validated, structured."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TerraformModule(BaseModel):
    """A self-contained Terraform module with explicit input/output interface."""

    name:    str = Field(description="Module name, e.g. 'networking', 'compute'")
    files:   Dict[str, str] = Field(default_factory=dict, description="filename → HCL content")
    outputs: List[str] = Field(default_factory=list, description="Output variable names exposed")
    inputs:  List[str] = Field(default_factory=list, description="Required input variables")
    validated: bool = False
    validation_log: str = ""


class MigrationWave(BaseModel):
    """One migration phase — group of resources with execution order."""

    order:       int
    name:        str
    description: str
    resources:   List[str] = Field(default_factory=list)
    blockers:    List[str] = Field(default_factory=list)


class MigrationRisk(BaseModel):
    category:   str
    detail:     str
    mitigation: str = ""


class DataMigrationScript(BaseModel):
    resource: str
    type:     str
    title:    str
    steps:    List[Dict[str, str]]
    notes:    str = ""


class MigrationPlanV2(BaseModel):
    """V2 migration plan — structured, validated, multi-module."""

    summary:    str
    assessment: str

    waves:          List[MigrationWave] = Field(default_factory=list)
    risks:          List[MigrationRisk] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)

    terraform_modules: List[TerraformModule] = Field(default_factory=list)
    root_module:       Optional[TerraformModule] = None

    data_migrations: List[DataMigrationScript] = Field(default_factory=list)

    validation_passed: bool = False
    validation_log:    List[str] = Field(default_factory=list)

    pipeline_log: List[str] = Field(default_factory=list)
