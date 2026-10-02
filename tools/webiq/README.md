# Microsoft Web IQ (candidate replacement for `web_search`)

`webiq-openapi.json` is the public Web IQ OpenAPI spec (`https://webiq.microsoft.ai/documentation/openapi.json`) trimmed to `/search/web` and `/browse`, with `servers` set to `https://api.microsoft.ai/v3`.

**Status: not enabled.** Web IQ access requires tenant enrollment in the Microsoft Frontier Preview Program. Tested 2026-10-02 from a Foundry agent with managed-identity auth: the token is accepted, but the call is rejected with
`AuthUnauthorizedEntryId: Application with entryId <foundry-account-identity-appId> is not authorized to access this service`.

## Option A — keyless (preferred)

Enroll the tenant in the Frontier Preview Program so Web IQ accepts the Foundry **account** managed identity (the `appid` claim of its token is the entry ID in the error). Then add this tool to the agent by creating a new version via the API (the portal only offers connection auth for OpenAPI tools):

```json
{
  "type": "openapi",
  "openapi": {
    "name": "webiq",
    "description": "Microsoft Web IQ web search and page browse, with source URLs.",
    "spec": "<contents of webiq-openapi.json>",
    "auth": { "type": "managed_identity", "security_scheme": { "audience": "https://api.microsoft.ai" } }
  }
}
```

## Option B — API key

Get a key from `https://webiq.microsoft.ai/profiles/`, store it in a Foundry project connection (custom keys, header `x-apikey`), and attach the tool with connection auth in the portal. Never put the key in instructions or this repo.

Web IQ also exposes an MCP server at `https://api.microsoft.ai/v3/mcp` (streamable HTTP, same auth) that could be used with Foundry's `mcp` tool instead.
