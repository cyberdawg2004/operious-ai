#!/usr/bin/env sh
set -eu

if [ -n "${OPERIOUS_KMS_SA_JSON:-}" ]; then
  credentials_path="${GOOGLE_APPLICATION_CREDENTIALS:-/tmp/operious-kms.json}"
  credentials_dir="$(dirname "$credentials_path")"

  mkdir -p "$credentials_dir"
  umask 077
  printf '%s' "$OPERIOUS_KMS_SA_JSON" > "$credentials_path"
  chmod 600 "$credentials_path"
  export GOOGLE_APPLICATION_CREDENTIALS="$credentials_path"
fi

exec "$@"
