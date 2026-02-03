# Rubrik On-Demand Backup Action

Trigger and monitor an on-demand Rubrik backup for a GitHub repository.  
The workflow fails if the backup does not succeed.

## Inputs

| Name | Required | Description |
|-----|----------|-------------|
| rsc-uri | yes | Rubrik Security Cloud base URL |
| client-id | yes | OAuth client ID |
| client-secret | yes | OAuth client secret |
| repository | yes | GitHub repository (owner/repo) |
| sla-name | yes | SLA Domain name |
| wait | no | Wait for completion (`true`/`false`) |

## Example

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
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python 
        uses: actions/setup-python@v5
        with:
          python-version: '3.x'

      - name: Run Rubrik On-Demand Backup
        uses: mwpreston/rubrik-on-demand-backup-action@main
        with:
          rsc-uri: ${{ secrets.RUBRIK_RSC_URI }}
          client-id: ${{ secrets.RUBRIK_CLIENT_ID }}
          client-secret: ${{ secrets.RUBRIK_CLIENT_SECRET }}
          repository: ${{ github.repository }}
          sla-name: "Gold"
          wait: "true"
