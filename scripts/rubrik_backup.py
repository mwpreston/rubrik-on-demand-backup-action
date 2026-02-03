import os
import sys
import requests


# -----------------------------
# Helpers
# -----------------------------

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def sleep_seconds(seconds: int) -> None:
    # No extra imports per your constraints; works on ubuntu-latest.
    os.system(f"sleep {int(seconds)}")


def normalize_base_uri(uri: str) -> str:
    return (uri or "").strip().rstrip("/")


def str_to_bool(value: str, default: bool = True) -> bool:
    """
    GitHub Action inputs are strings.
    Treat 'false' (case-insensitive) as False, everything else as True.
    """
    if value is None:
        return default
    return value.strip().lower() != "false"


def is_transient_activityseries_500(errors) -> bool:
    """
    Detect the specific transient failure you saw:
    - message: 'An unexpected internal error occurred.'
    - path: ['activitySeries']
    - extensions.code: 500
    """
    try:
        for e in errors or []:
            if e.get("path") == ["activitySeries"]:
                ext = e.get("extensions") or {}
                code = ext.get("code")
                msg = (e.get("message") or "").lower()
                if code == 500 and "unexpected internal error" in msg:
                    return True
    except Exception:
        pass
    return False


def extract_trace_id(errors):
    try:
        if not errors:
            return None
        ext = (errors[0].get("extensions") or {})
        trace = (ext.get("trace") or {})
        return trace.get("traceId")
    except Exception:
        return None


def post_graphql(rsc_uri: str, token: str, query: str, variables: dict, timeout: int = 30):
    """
    General GraphQL POST helper.
    Returns parsed JSON dict on success, or None on any failure (prints to stderr).
    """
    url = f"{rsc_uri}/api/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
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
        "grant_type": "client_credentials"
    }
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    return response.json().get("access_token")


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

    # Keeping your variable structure as-is (no query changes)
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

    return nodes[0].get("id")


def get_rubrik_repo_id(rsc_uri, token, github_repo):
    """Searches RSC for the GitHub repository ID using the full name."""
    if not github_repo:
        eprint("get_rubrik_repo_id: github_repo must be provided")
        return None

    # Extract only the repository name if input includes owner (e.g., 'owner/repo' -> 'repo')
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

    return nodes[0].get("id")


# -----------------------------
# Backup + Monitor
# -----------------------------

def trigger_on_demand_snapshot(rsc_uri, token, repo_id, sla_domain_id):
    """
    Triggers the on-demand snapshot and returns taskchainId.
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


def wait_for_activity_series(rsc_uri, token, activity_series_id, poll_seconds=10):
    """
    Polls EventSeriesDetailsQuery until lastActivityStatus is exactly 'Success' or 'Failure'.
    IMPORTANT: Handles transient 'activitySeries' GraphQL 500 errors by sleeping and retrying.
    """
    url = f"{rsc_uri}/api/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

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

    payload = {"query": query, "variables": variables}

    status = None
    while status not in ("Success", "Failure"):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            eprint(f"retrieve task status: request failed: {e}")
            return None

        try:
            result = resp.json()
        except ValueError:
            eprint("retrieve task status: response was not valid JSON")
            return None

        if result.get("errors"):
            # NEW: Treat specific activitySeries 500 as transient
            if is_transient_activityseries_500(result["errors"]):
                trace_id = extract_trace_id(result["errors"])
                if trace_id:
                    print(f"activitySeries not ready yet (transient 500). traceId={trace_id}. Waiting…")
                else:
                    print("activitySeries not ready yet (transient 500). Waiting…")
                sleep_seconds(poll_seconds)
                continue

            eprint(f"retrieve task status: GraphQL errors: {result['errors']}")
            return None

        try:
            status = result["data"]["activitySeries"]["lastActivityStatus"]
        except (TypeError, KeyError):
            eprint(f"retrieve task status: unexpected response shape: {result}")
            return None

        print("Current Job Status:", status)

        if status in ("Success", "Failure"):
            break

        sleep_seconds(poll_seconds)

    return status


def take_on_demand_snapshot(rsc_uri, token, repo_id, sla_domain_id, wait_for_completion):
    """
    Triggers the on-demand snapshot; optionally waits for Success/Failure.
    Returns 'Triggered' if not waiting, else 'Success' or 'Failure'.
    """
    taskchain_id = trigger_on_demand_snapshot(rsc_uri, token, repo_id, sla_domain_id)
    if not taskchain_id:
        return None

    print("Triggered taskchain ID:", taskchain_id)

    # Give the series a moment to appear (your original behavior)
    sleep_seconds(10)

    if not wait_for_completion:
        return "Triggered"

    return wait_for_activity_series(rsc_uri, token, taskchain_id, poll_seconds=10)


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

    missing = []
    if not rsc_uri:
        missing.append("RUBRIK_RSC_URI")
    if not client_id:
        missing.append("RUBRIK_CLIENT_ID")
    if not client_secret:
        missing.append("RUBRIK_CLIENT_SECRET")
    if not github_repo:
        missing.append("GITHUB_REPO_NAME")
    if not sla_domain_name:
        missing.append("RUBRIK_SLA_DOMAIN_NAME")

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
