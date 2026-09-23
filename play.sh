#!/bin/zsh
# usage: play.sh [-v] yellow from coldplay   → classifies "/play yellow from coldplay" with Jev (-v: show payloads)
#
# auth, in order:
#   1. AI_GATEWAY_API_KEY, if set
#   2. a Vercel OIDC token cached in .env.gw, refreshed with `vercel env pull`
#      from VERCEL_PROJECT_DIR (any Vercel-linked project; set it in .env.local)
DIR=${0:A:h}
[[ -f $DIR/.env.local ]] && source $DIR/.env.local

if [[ -z $AI_GATEWAY_API_KEY ]]; then
  ENV=$DIR/.env.gw
  token() { grep '^VERCEL_OIDC_TOKEN=' $ENV 2>/dev/null | cut -d= -f2- | tr -d '"' }
  T=$(token)
  if [[ -z $T ]] || [[ $(curl -s -o /dev/null -w '%{http_code}' https://ai-gateway.vercel.sh/typesafe/v1/models -H "Authorization: Bearer $T") != 200 ]]; then
    [[ -z $VERCEL_PROJECT_DIR ]] && { echo "set AI_GATEWAY_API_KEY, or VERCEL_PROJECT_DIR in .env.local" >&2; exit 1 }
    echo "(refreshing Vercel OIDC token...)" >&2
    (cd $VERCEL_PROJECT_DIR && vercel env pull $ENV --yes >/dev/null 2>&1)
    T=$(token)
  fi
  export AI_GATEWAY_API_KEY=$T
fi

V=(); [[ $1 == -v ]] && { V=(-v); shift }
if (( $# )); then set -- "/play $*"; fi
exec uv run -q $DIR/dj_router.py $V "$@"
