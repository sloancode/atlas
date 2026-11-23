#!/usr/bin/env bash
# Checks the Shopify credentials in backend/.env by asking Shopify for a token.
# Prints only lengths/prefixes of your values and Shopify's answer -- never the
# secret or the token. Safe to run while ATLAS is stopped or running.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/backend/.env"
[ -f "$ENV_FILE" ] || { echo "No backend/.env found. Run ./scripts/setup-linux.sh first."; exit 1; }

val() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'\'' ]*//' -e 's/["'\'' ]*$//'; }
DOMAIN="$(val SHOPIFY_STORE_DOMAIN)"
CID="$(val SHOPIFY_CLIENT_ID)"
CS="$(val SHOPIFY_CLIENT_SECRET)"

echo "Store domain:   ${DOMAIN:-(missing)}"
echo "Client ID:      length ${#CID} (expected 32)"
echo "Client secret:  starts with '${CS:0:6}', length ${#CS} (expected 'shpss_', 38)"
problems=0
[ -z "$DOMAIN" ] && { echo "  -> SHOPIFY_STORE_DOMAIN is empty."; problems=1; }
[ ${#CID} -ne 32 ] && { echo "  -> Client ID looks wrong. Copy it again from the Dev Dashboard."; problems=1; }
[[ "$CS" != shpss_* ]] && { echo "  -> Client secret should start with shpss_. It may be pasted in the wrong line."; problems=1; }
[ "$CID" = "$CS" ] && { echo "  -> Client ID and secret are identical; one was pasted twice."; problems=1; }
[ $problems -ne 0 ] && { echo; echo "Fix backend/.env, then run this check again."; exit 1; }

URL="${SHOPIFY_TOKEN_URL_OVERRIDE:-https://$DOMAIN/admin/oauth/access_token}"
echo
echo "Asking Shopify for a token..."
BODY="$(curl -sS --max-time 20 -w $'\n%{http_code}' -X POST "$URL" \
  -H 'Accept: application/json' \
  --data-urlencode grant_type=client_credentials \
  --data-urlencode "client_id=$CID" \
  --data-urlencode "client_secret=$CS" 2>&1)"
CODE="${BODY##*$'\n'}"
BODY="${BODY%$'\n'*}"
unset CS

if [ "$CODE" = "200" ] && grep -q '"access_token"' <<<"$BODY"; then
  echo "SUCCESS: Shopify accepted the credentials. Restart ATLAS and run the live check."
  exit 0
fi

echo "Shopify answered HTTP $CODE."
REASON="$(sed -e 's/"access_token":"[^"]*"/"access_token":"(hidden)"/g' -e 's/<[^>]*>/ /g' <<<"$BODY" \
  | tr -s ' \n' ' ' | cut -c1-300)"
echo "Shopify's reason: ${REASON:-(none given)}"
echo
case "$REASON" in
  *invalid_client*|*"Oauth error"*|*"invalid_request"*)
    echo "Likely cause: the client ID/secret don't match. Copy the CURRENT secret from"
    echo "Dev Dashboard -> app named from claude -> Settings and save it again." ;;
  *"not installed"*|*shop_not_permitted*|*"not permitted"*)
    echo "Likely cause: this app isn't installed on $DOMAIN, or belongs to a different"
    echo "organization than the store. Install it on the store from the Dev Dashboard." ;;
  *)
    echo "Send the 'Shopify answered' and 'Shopify's reason' lines above (they contain no secret)." ;;
esac
exit 1
