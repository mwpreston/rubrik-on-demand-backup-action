import os
import sys
import requests


# -----------------------------
# Small helpers (readability)
# -----------------------------

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def sleep10():
    # You asked to avoid extra libs; this works fine on ubuntu-latest runners.
    os.system("sleep 10")


def normalize_base_uri(uri):
    return (uri or "").strip().rstrip("/")


def str_to_bool(value, default=True):
    """
    Interprets typical GitHub Actions string inputs.
    - "false" (any case) -> False
    - anything else -> True
    """
    if value is None:
        return default
    return value.strip().lower() != "false"


def post_graphql(rsc_uri, token, query, variables, timeout=30):
    """
    Posts a GraphQL request to RSC and returns the parsed JSON.
    Consistently handles HTTP + JSON + GraphQL errors.
    """
    url = f"{rsc_uri}/api/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": variables}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        eprint(f"GraphQL request failed: {e}")
        return None

    try:
        data = resp.json()
    except ValueError:
        eprint("GraphQL response was not valid JSON")
        return None

    if data.get("errors"):
        eprint(f"GraphQL errors: {data['errors']}")
        return None

    return data


# -----------------------------
# Auth
# -----------------------------

def get_access_token(rsc_uri, client_id, client_secret):
    url = f"{rsc_uri}/api/client_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json().get("access_token")


# -----------------------------
# Lookups
# -----------------------------

def get_rubrik_sla_domain_id(rsc_uri, token, sla_name):
    query = """
    query GetSLADomainID($filter: [GlobalSlaFilterInput!]) {
      slaDomains(filter: $filter) {
        nodes {
          id
          name
        }
      }
    }
    """.strip()

    # Keeping your variable structure as-is (since you said it works)
    variables = {
        "filter": {
            "field": "NAME",
            "text": sla_name
        }
    }

    result = post_graphql(rsc_uri, token, query, variables)
    if not result:
        return None

    try:
        nodes = result["data"]["slaDomains"]["nodes"]
    except (TypeError, KeyError):
        eprint(f"get_rubrik_sla_domain_id: unexpected response shape: {result}")
        return None

    if not nodes:
        return None

    # Return first match
    return nodes[0].get("id")


def get_rubrik_repo_id(rsc_uri, token, github_repo):
    """
    Searches RSC for the GitHub repository ID.
    github_repo can be 'owner/repo' or just 'repo' — we use repo name for NAME filter.
    """
    if not github_repo:
        eprint("get_rubrik_repo_id: github_repo must be provided")
        return None

    repo_name = github_repo.split("/")[-1]

    query = """
    query GithubReposListQuery($filter: [Filter!], $ancestorId: String!, $queryType: QueryType!) {
      gitHubRepositories(filter: $filter, ancestorId: $ancestorId, queryType: $queryType) {
        nodes {
          id
          name
          orgName
        }
      }
    }
    """.strip()

    variables = {
        "filter": [
            {
                "field": "NAME",
                "texts": repo_name
            }
        ],
        "ancestorId": "GITHUB_ROOT",
        "queryType": "DESCENDANTS"
    }

    result = post_graphql(rsc_uri, token, query, variables)
    if not result:
        return None

    try:
        nodes = result["data"]["gitHubRepositories"]["nodes"]
    except (TypeError, KeyError):
        eprint(f"get_rubrik_repo_id: unexpected response shape: {result}")
        return None

    if not nodes:
        return None

    # Return first match
    return nodes[0].get("id")


# -----------------------------
# Backup + Monitor
# -----------------------------

def trigger_on_demand_snapshot(rsc_uri, token, repo_id, sla_domain_id):
    """
    Triggers the on-demand snapshot and returns taskchainId (activitySeriesId).
    """
    mutation = """
    mutation GithubTakeOnDemandSnapshotMutation($input: BackupDevOpsRepositoryInput!) {
      backupDevOpsRepository(input: $input) {
        taskchainId
        errorMessage
        __typename
      }
    }
    """.strip()

    variables = {
        "input": {
            "repositoryId": repo_id,
            "retentionSlaId": sla_domain_id
        }
    }

    result = post_graphql(rsc_uri, token, mutation, variables)
    if not result:
        return None

    try:
        taskchain_id = result["data"]["backupDevOpsRepository"]["taskchainId"]
    except (TypeError, KeyError):
        eprint(f"trigger_on_demand_snapshot: unexpected response shape: {result}")
        return None

    if not taskchain_id:
        eprint(f"trigger_on_demand_snapshot: no taskchainId returned: {result}")
        return None

    return taskchain_id


def wait_for_activity_series(rsc_uri, token, activity_series_id):
    """
    Polls EventSeriesDetailsQuery until lastActivityStatus is exactly 'Success' or 'Failure'.
    Returns 'Success' or 'Failure' on completion.
    """
    query = """
    query EventSeriesDetailsQuery($activitySeriesId: UUID!, $clusterUuid: UUID) {
      activitySeries(
        input: {activitySeriesId: $activitySeriesId, clusterUuid: $clusterUuid}
      ) {
        lastActivityStatus
        activityConnection {
          nodes {
            activityInfo
            errorInfo
            message
            status
          }
        }
      }
    }
    """.strip()

    variables = {
        "activitySeriesId": activity_series_id,
        "clusterUuid": "00000000-0000-0000-0000-000000000000"
    }

    # Prime status
    status = None

    while status not in ("Success", "Failure"):
        result = post_graphql(rsc_uri, token, query, variables)
        if not result:
            return None

        try:
            status = result["data"]["activitySeries"]["lastActivityStatus"]
        except (TypeError, KeyError):
            eprint(f"wait_for_activity_series: unexpected response shape: {result}")
            return None

        print("Current Job Status:", status)

        if status in ("Success", "Failure"):
            break

        sleep10()

    return status


def take_on_demand_snapshot(rsc_uri, token, repo_id, sla_domain_id, wait_for_completion):
    """
    Triggers snapshot; optionally waits.
    Returns:
      - 'Triggered' if not waiting
      - 'Success' or 'Failure' if waiting completes
      - None on error
    """
    taskchain_id = trigger_on_demand_snapshot(rsc_uri, token, repo_id, sla_domain_id)
    if not taskchain_id:
        return None

    print("Triggered taskchain ID:", taskchain_id)

    # Give the series a moment to appear (your original behavior)
    sleep10()

    if not wait_for_completion:
        return "Triggered"

    return wait_for_activity_series(rsc_uri, token, taskchain_id)


# -----------------------------
# Main
# -----------------------------

def main():
    rsc_uri = normalize_base_uri(os.getenv("RUBRIK_RSC_URI"))
    client_id = (os.getenv("RUBRIK_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("RUBRIK_CLIENT_SECRET") or "").strip()
    github_repo = (os.getenv("GITHUB_REPO_NAME") or "").strip()
    sla_domain_name = (os.getenv("RUBRIK_SLA_DOMAIN_NAME") or "").strip()
    wait_for_completion = str_to_bool(os.getenv("WAIT_FOR_COMPLETION", "true"), default=True)

    # Basic validation
    missing = []
    if not rsc_uri: missing.append("RUBRIK_RSC_URI")
    if not client_id: missing.append("RUBRIK_CLIENT_ID")
    if not client_secret: missing.append("RUBRIK_CLIENT_SECRET")
    if not github_repo: missing.append("GITHUB_REPO_NAME")
    if not sla_domain_name: missing.append("RUBRIK_SLA_DOMAIN_NAME")

    if missing:
        eprint("Missing required environment variables:", ", ".join(missing))
        return 1

    try:
        token = get_access_token(rsc_uri, client_id, client_secret)
        if not token:
            eprint("Failed to obtain access token.")
            return 1

        repo_id = get_rubrik_repo_id(rsc_uri, token, github_repo)
        print("Working with repo id:", repo_id)
        if not repo_id:
            eprint("Repo not found in Rubrik (repo_id is empty).")
            return 1

        sla_domain_id = get_rubrik_sla_domain_id(rsc_uri, token, sla_domain_name)
        print("Working with SLA domain id:", sla_domain_id)
        if not sla_domain_id:
            eprint("SLA Domain not found in Rubrik (sla_domain_id is empty).")
            return 1

        final_status = take_on_demand_snapshot(rsc_uri, token, repo_id, sla_domain_id, wait_for_completion)

        if not final_status:
            eprint("Backup failed due to earlier error.")
            return 1

        # GitHub Actions semantics:
        # - if wait=false, Triggered is a success
        # - if wait=true, Success is success; Failure fails the workflow
        if not wait_for_completion:
            print("✅ Backup triggered successfully (not waiting). Status:", final_status)
            return 0

        if final_status == "Success":
            print("✅ Backup completed successfully. Status:", final_status)
            return 0

        eprint("❌ Backup completed with Failure. Status:", final_status)
        return 1

    except Exception as e:
        eprint(f"❌ Critical Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
