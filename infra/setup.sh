#!/usr/bin/env bash
# Keyless Azure Maps for the agents' azure_maps OpenAPI tool.
# Creates a Maps account with local (key) auth disabled and grants the Foundry
# ACCOUNT's system-assigned identity "Azure Maps Data Reader". Foundry's OpenAPI
# tool with managed_identity auth gets its token from that identity - not from
# the project identity or the per-agent identity.
#
# Usage: FOUNDRY_ACCOUNT=<name> MAPS_ACCOUNT=<name> ./infra/setup.sh   (reads .env for the rest)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${AZURE_SUBSCRIPTION_ID:?}" "${AZURE_RESOURCE_GROUP:?}" "${FOUNDRY_ACCOUNT:?}" "${MAPS_ACCOUNT:?}"

RG_ID="/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}"
MAPS_ID="${RG_ID}/providers/Microsoft.Maps/accounts/${MAPS_ACCOUNT}"

az rest --method put --url "https://management.azure.com${MAPS_ID}?api-version=2023-06-01" \
  --body '{"location":"global","kind":"Gen2","sku":{"name":"G2"},"properties":{"disableLocalAuth":true}}' -o none

CLIENT_ID=$(az rest --method get --url "https://management.azure.com${MAPS_ID}?api-version=2023-06-01" \
  --query properties.uniqueId -o tsv)
FOUNDRY_MI=$(az rest --method get \
  --url "https://management.azure.com${RG_ID}/providers/Microsoft.CognitiveServices/accounts/${FOUNDRY_ACCOUNT}?api-version=2025-06-01" \
  --query identity.principalId -o tsv)

az role assignment create --assignee-object-id "$FOUNDRY_MI" --assignee-principal-type ServicePrincipal \
  --role "Azure Maps Data Reader" --scope "$MAPS_ID" -o none

echo "Set AZURE_MAPS_CLIENT_ID=${CLIENT_ID} in .env (role assignments can take a few minutes to apply)."
