# AWS Agent Toolkit / Codex Integration

## Project AWS profile
Use this AWS CLI profile for this repository:

`Universal-Creative-Agent-GitHub`

## Region
The repository's existing AWS Device Farm workflow uses `us-west-2` as its fallback/default operational region. Treat this as the repository's current AWS operational region unless the authenticated AWS project/account configuration explicitly reports a different default.

## Codex / AWS MCP
When AWS Agent Toolkit is installed in the Codex host, the generated `aws-mcp` MCP server entry must use:

```json
"env": {
  "AWS_MCP_PROXY_PROFILES": "Universal-Creative-Agent-GitHub"
}
```

Do not replace the generated `command`, `args`, `timeout`, or `transport` values from Agent Toolkit.

## Authentication
Do not store AWS access keys or secret keys in this repository. Authenticate through:

```bash
aws configure set region us-west-2 --profile Universal-Creative-Agent-GitHub
aws login --region us-west-2 --profile Universal-Creative-Agent-GitHub
aws sts get-caller-identity --profile Universal-Creative-Agent-GitHub
```

Agent Toolkit itself must be configured through `us-east-1`:

```bash
aws configure agent-toolkit --yes --region us-east-1 --profile Universal-Creative-Agent-GitHub
aws agent-toolkit list-available-skills --region us-east-1 --profile Universal-Creative-Agent-GitHub
```

## Project precedence
Preserve existing project instructions and do not overwrite them when AWS Agent Toolkit rules are appended. AWS Agent Toolkit rules must be kept between stable markers if they are later added to this file.
