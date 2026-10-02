# Microsoft Web IQ (candidate replacement for `web_search`)

`webiq-openapi.json` is the public Web IQ OpenAPI spec (`https://webiq.microsoft.ai/documentation/openapi.json`) trimmed to `/search/web` and `/browse`, with `servers` set to `https://api.microsoft.ai/v3`.

**Status: not enabled.** Web IQ is limited access. Tested 2026-10-02 from a Foundry agent with managed-identity auth: the token is accepted, but the call is rejected with
`AuthUnauthorizedEntryId: Application with entryId <foundry-account-identity-appId> is not authorized to access this service`.

## Option A — keyless (preferred)

Ask the Web IQ team to authorise the Foundry **account** managed identity's application ID (the `appid` claim of its token; for this POV it is the ID in the error above). Then add this tool to the agent by creating a new version via the API (the portal only offers connection auth for OpenAPI tools):

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
