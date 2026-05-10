"""AWS credential management for Phase 0."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

_CFG = Config(retries={"max_attempts": 2, "mode": "standard"}, connect_timeout=5, read_timeout=10)

# Cheap read calls that confirm each service is accessible.
_PROBES: List[Tuple[str, str, Dict[str, Any]]] = [
    ("ec2",                   "describe_instances",        {"MaxResults": 5}),
    ("ec2",                   "describe_vpcs",             {}),
    ("rds",                   "describe_db_instances",     {"MaxRecords": 20}),
    ("s3",                    "list_buckets",              {}),
    ("lambda",                "list_functions",            {"MaxItems": 1}),
    ("elasticloadbalancing",  "describe_load_balancers",   {"PageSize": 1}),
    ("dynamodb",              "list_tables",               {"Limit": 1}),
    ("ecs",                   "list_clusters",             {"maxResults": 1}),
    ("iam",                   "list_roles",                {"MaxItems": 1}),
    ("secretsmanager",        "list_secrets",              {"MaxResults": 1}),
]


def build_session(
    method: str,
    region: str,
    profile: Optional[str] = None,
    access_key_id: Optional[str] = None,
    secret_access_key: Optional[str] = None,
    session_token: Optional[str] = None,
) -> boto3.Session:
    if method == "profile":
        return boto3.Session(profile_name=profile or None, region_name=region)
    if method == "static_keys":
        return boto3.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            aws_session_token=session_token or None,
            region_name=region,
        )
    # "default" — let boto3 walk the standard chain
    return boto3.Session(region_name=region)


def verify_identity(session: boto3.Session) -> Dict[str, str]:
    sts = session.client("sts", config=_CFG)
    r = sts.get_caller_identity()
    return {"account_id": r["Account"], "arn": r["Arn"], "user_id": r["UserId"]}


def probe_permissions(session: boto3.Session, region: str) -> List[Dict[str, Any]]:
    results = []
    for service, action, kwargs in _PROBES:
        try:
            client = session.client(service, region_name=region, config=_CFG)
            getattr(client, action)(**kwargs)
            results.append({"service": service, "action": action, "ok": True})
        except ClientError as e:
            code = e.response["Error"]["Code"]
            denied = code in ("AccessDenied", "UnauthorizedOperation", "AccessDeniedException")
            results.append({"service": service, "action": action, "ok": not denied, "note": code})
        except Exception as e:
            results.append({"service": service, "action": action, "ok": False, "note": str(e)[:120]})
    return results


def list_org_accounts(session: boto3.Session) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """Return (accounts, error). Empty list + error string when org is unavailable."""
    try:
        org = session.client("organizations", region_name="us-east-1", config=_CFG)
        paginator = org.get_paginator("list_accounts")
        accounts = []
        for page in paginator.paginate():
            for a in page.get("Accounts", []):
                accounts.append({
                    "account_id": a["Id"],
                    "name": a["Name"],
                    "email": a.get("Email", ""),
                    "status": a["Status"],
                })
        return accounts, None
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "AWSOrganizationsNotInUseException":
            return [], "single_account"          # not an error — just no org
        if code in ("AccessDeniedException", "AccessDenied"):
            return [], "no_org_permission"
        return [], str(e)
    except Exception as e:
        return [], str(e)


def assume_role(
    session: boto3.Session,
    role_arn: str,
    session_name: str = "cloud-migration",
) -> boto3.Session:
    sts = session.client("sts", config=_CFG)
    r = sts.assume_role(RoleArn=role_arn, RoleSessionName=session_name, DurationSeconds=3600)
    c = r["Credentials"]
    return boto3.Session(
        aws_access_key_id=c["AccessKeyId"],
        aws_secret_access_key=c["SecretAccessKey"],
        aws_session_token=c["SessionToken"],
        region_name=session.region_name,
    )
