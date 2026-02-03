# Rubrik On-Demand Backup Action

Trigger and optionally **enforce** a Rubrik on-demand backup as part of your GitHub Actions workflow.

This action enables **backup-as-code** for GitHub repositories by integrating Rubrik directly into your CI/CD pipeline. You can use it to automatically protect repository data **before or after a merge**, and optionally **block merges** until a backup completes successfully.

---

## Why this exists

For teams using Infrastructure as Code, GitOps, and CI/CD pipelines, data protection often lives **outside** the delivery workflow.

This action brings backups into the same place you already enforce:
- tests
- security scans
- policy checks

With this action, a backup can become:
- a **non-blocking safety net** on pull requests
- a **hard gate** on merges to `main`
- an auditable, repeatable part of your delivery process

No dashboards. No manual steps. Just pipelines.

---

## How it works

1. Triggers a Rubrik on-demand snapshot for the specified GitHub repository
2. Optionally waits for the backup to complete
3. Fails the workflow if the backup does not succeed (when waiting is enabled)

When `wait: "true"` is used, the workflow will not complete until the backup reaches a terminal state (`Success` or `Failure`).

---

## Inputs

| Name | Required | Description |
|-----|----------|-------------|
| `rsc-uri` | yes | Rubrik Security Cloud base URL (https://domain.my.rubrik.com) |
| `client-id` | yes | OAuth client ID |
| `client-secret` | yes | OAuth client secret |
| `repository` | yes | GitHub repository (`owner/repo`) |
| `sla-name` | yes | SLA Domain name to apply |
| `wait` | no | Wait for completion (`true` / `false`, default: `true`) |

---

## Usage examples

### Enforce a backup on merge to `main` (blocking)

This pattern ensures a backup completes successfully **before the merge is allowed**.

```yaml
name: Rubrik On-Demand Backup

on:
  push:
    branches:
      - main

jobs:
  backup:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.x'

      - name: Run Rubrik On-Demand Backup
        uses: mwpreston/rubrik-on-demand-backup-action@v1
        with:
          rsc-uri: ${{ secrets.RUBRIK_RSC_URI }}
          client-id: ${{ secrets.RUBRIK_CLIENT_ID }}
          client-secret: ${{ secrets.RUBRIK_CLIENT_SECRET }}
          repository: ${{ github.repository }}
          sla-name: Gold
          wait: "true"
```

---

### Trigger a backup without blocking (fire-and-forget)

Useful for pull requests or lower-risk repositories.

```yaml
wait: "false"
```

The workflow will succeed immediately after the backup is triggered.

---

## Notes and considerations

- The Rubrik endpoint must be reachable from the runner  
  - Private DNS endpoints require a self-hosted runner
- OAuth credentials should be scoped with least privilege
- Transient Rubrik API errors are handled automatically during status polling

---

## When to use this

This action is well suited for:
- Infrastructure repositories (Terraform, CloudFormation, Pulumi)
- GitOps workflows
- Repositories where backups are a compliance or recovery requirement
- Teams looking to enforce operational hygiene through CI/CD

---

## Why this approach

Backups shouldn’t be an afterthought.

By making them part of the pipeline, they become:
- visible
- repeatable
- enforceable
