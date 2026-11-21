#!/bin/bash
# usage: dl.sh name url
set -u
D=${DLDIR:-/workspace/data/datasets/wider_face/archives}; L=/tmp/rn3/dl_$1.log
ts(){ echo "utc=$(date -u +%FT%TZ) berlin=$(TZ=Europe/Berlin date +%FT%T%:z)"; }
{ echo "start $(ts) url=$2"; echo "df_before_avail=$(df -B1 --output=avail / | tail -1)"
curl -sS -L --fail -m 3600 -D /tmp/rn3/dl_$1.headers -o $D/$1.part -w 'http=%{http_code} bytes=%{size_download} final=%{url_effective} ctype=%{content_type}\n' "$2"; echo "curl_exit=$?"
echo "end $(ts)"; echo "df_after_avail=$(df -B1 --output=avail / | tail -1)"; } >> $L 2>&1
