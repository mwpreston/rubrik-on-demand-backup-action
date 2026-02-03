import os
import requests
import sys

def get_access_token(rsc_uri, client_id, client_secret):
    url = f"{rsc_uri}/api/client_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials"
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json().get("access_token")

def get_rubrik_sla_domain_id(rsc_uri, token, sla_name):
    url = f"{rsc_uri}/api/graphql"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"} 

    query = """query GetSLADomainID($filter: [GlobalSlaFilterInput!]) {
        slaDomains(filter: $filter) {
            nodes {
            id
            name
            }
        }
    }""".strip()

    variables = {
        "filter": [{
            "field": "NAME",
            "text": sla_name
        }]
    }

    payload = {
        "query": query,
        "variables": variables,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"get_rubrik_sla_domain_id: request failed: {e}", file=sys.stderr)
        return None

    try:
        result = response.json()
    except ValueError:
        print("get_rubrik_sla_domain_id: response was not valid JSON", file=sys.stderr)
        return None

    if result.get("errors"):
        print(f"get_rubrik_sla_domain_id: GraphQL errors: {result['errors']}", file=sys.stderr)
        return None

    try:
        nodes = result["data"]["slaDomains"]["nodes"]
    except (TypeError, KeyError):
        print(f"get_rubrik_sla_domain_id: unexpected response shape: {result}", file=sys.stderr)
        return None

    if not nodes:
        return None

    # Return the first match — caller controls the search string
    return nodes[0].get("id")

def get_rubrik_repo_id(rsc_uri, token, github_repo):
    """Searches RSC for the GitHub repository ID using the full name."""
    url = f"{rsc_uri}/api/graphql"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"} 

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

    if not github_repo:
        print("get_rubrik_repo_id: github_repo must be provided", file=sys.stderr)
        return None

    # Extract only the repository name if GITHUB_REPOSITORY includes the owner (e.g., 'owner/repo' -> 'repo')
    repo_name = github_repo.split("/")[-1]

    variables = {
        "filter": [
            {
                "field": "NAME",
                "texts": repo_name
            }
        ],
        "ancestorId":  "GITHUB_ROOT",
        "queryType": "DESCENDANTS"
    }

    payload = {
        "query": query,
        "variables": variables,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"get_rubrik_repo_id: request failed: {e}", file=sys.stderr)
        return None

    try:
        result = response.json()
    except ValueError:
        print("get_rubrik_repo_id: response was not valid JSON", file=sys.stderr)
        return None

    if result.get("errors"):
        print(f"get_rubrik_repo_id: GraphQL errors: {result['errors']}", file=sys.stderr)
        return None

    try:
        nodes = result["data"]["gitHubRepositories"]["nodes"]
    except (TypeError, KeyError):
        print(f"get_rubrik_repo_id: unexpected response shape: {result}", file=sys.stderr)
        return None

    if not nodes:
        return None

    # Return the first match — caller controls the search string
    return nodes[0].get("id")

def take_on_demand_snapshot(rsc_uri, token, repo_id, sla_domain_id,wait_for_completion):
    """Triggers the on-demand snapshot in Rubrik."""
    url = f"{rsc_uri}/api/graphql"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    mutation = """mutation GithubTakeOnDemandSnapshotMutation($input: BackupDevOpsRepositoryInput!) {
        backupDevOpsRepository(input: $input) {
            taskchainId
            errorMessage
            __typename
        }
        }""".strip()
    
    variables = {
        "input": {
            "repositoryId": repo_id,
            "retentionSlaId": sla_domain_id
        }
    }

    payload = {
        "query": mutation,
        "variables": variables,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"take_on_demand_snapshot: request failed: {e}", file=sys.stderr)
        return None

    try:
        result = response.json()
    except ValueError:
        print("take_on_demand_snapshot: response was not valid JSON", file=sys.stderr)
        return None


    if result.get("errors"):
        print(f"take_on_demand_snapshot: GraphQL errors: {result['errors']}", file=sys.stderr)
        return None
    
    try:
        taskchain = result["data"]["backupDevOpsRepository"]["taskchainId"]
    except (TypeError, KeyError):
        print(f"take_on_demand_snapshot: unexpected response shape: {result}", file=sys.stderr)
        return None

    if not taskchain:
        print(f"take_on_demand_snapshot: no taskchainId returned in response: {result}", file=sys.stderr)
        return None

    print("Triggered taskchain ID:", taskchain)
    os.system("sleep 10")
    #return taskchain
    # Monitor task chain until SUCCESS of FAILURE

    if wait_for_completion.lower() != "false":
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
            }""".strip()
        
        variables = {
            "activitySeriesId": taskchain,
            "clusterUuid": "00000000-0000-0000-0000-000000000000"
        }

        payload = {
            "query": query,
            "variables": variables
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"retrieve task status: request failed: {e}", file=sys.stderr)
            return None

        try:
            result = response.json()
        except ValueError:
            print("retrieve task status: response was not valid JSON", file=sys.stderr)
            return None


        if result.get("errors"):
            print(f"retrieve task status: GraphQL errors: {result['errors']}", file=sys.stderr)
            return None
        
        try:
            status = result["data"]["activitySeries"]["lastActivityStatus"]
            print("Current Job Status:", status)
        except (TypeError, KeyError):
            print(f"retrieve task status: unexpected response shape: {result}", file=sys.stderr)
            return None

        while status not in ("Success", "Failure"):
            print("Current Job Status:", status)
            os.system("sleep 10")
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            result = response.json()
            status = result["data"]["activitySeries"]["lastActivityStatus"]
    else:
        status = "Triggered"
    
    return status

if __name__ == "__main__":
    rsc_uri = os.getenv("RUBRIK_RSC_URI").strip().rstrip("/")
    client_id = os.getenv("RUBRIK_CLIENT_ID")
    client_secret = os.getenv("RUBRIK_CLIENT_SECRET")
    github_repo = os.getenv("GITHUB_REPO_NAME")
    sla_domain_name = os.getenv("RUBRIK_SLA_DOMAIN_NAME")
    wait_for_completion = os.getenv("WAIT_FOR_COMPLETION", "true")
    try:
        auth_token = get_access_token(rsc_uri, client_id, client_secret)
        repo_id = get_rubrik_repo_id(rsc_uri, auth_token, github_repo)
        print("working with repo id:", repo_id)
        sla_domain_id = get_rubrik_sla_domain_id(rsc_uri, auth_token, sla_domain_name)
        print("working with sla domain id:", sla_domain_id)

        statuses = take_on_demand_snapshot(rsc_uri, auth_token, repo_id, sla_domain_id, wait_for_completion)
        print("✅ Backup triggered successfully. Statuses:", statuses)
        sys.exit(0)
        
    except Exception as e:
        print(f"❌ Critical Error: {e}")
        sys.exit(1)