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
- uses: mwpreston/rubrik-on-demand-backup-action@v1
  with:
    rsc-uri: ${{ secrets.RUBRIK_RSC_URI }}
    client-id: ${{ secrets.RUBRIK_CLIENT_ID }}
    client-secret: ${{ secrets.RUBRIK_CLIENT_SECRET }}
    repository: ${{ github.repository }}
    sla-name: Gold
    wait: "true"
