#!/usr/bin/env bash
# Fill /etc/observation-watch/watch.env for the observation watcher (sourced by install.sh; tested on its own).
#
#   ensure_watch_env <ops-notify.env> <watch.env>
#
# LINE is the watcher's primary channel: LINE_CHANNEL_ACCESS_TOKEN and LINE_RECIPIENT_ID are REQUIRED (the function fails
# when they are in neither file).  Telegram is only the fallback: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are copied when the
# source has them, and a missing source file or a missing setting is only a warning.  A variable already in watch.env is
# never touched.  Values are never printed; the file is created and appended to with umask 077.

ensure_watch_env() {
  local ops_env=$1 watch_env=$2 spec var required line
  ( umask 077; touch "$watch_env" ) || { echo "INSTALL_FAILED: cannot create $watch_env" >&2; return 1; }
  for spec in LINE_CHANNEL_ACCESS_TOKEN:yes LINE_RECIPIENT_ID:yes TELEGRAM_BOT_TOKEN:no TELEGRAM_CHAT_ID:no; do
    var=${spec%%:*}; required=${spec##*:}
    if grep -q "^${var}=" "$watch_env"; then continue; fi
    if [[ ! -r $ops_env ]]; then
      if [[ $required == yes ]]; then
        echo "INSTALL_FAILED: no $ops_env to copy the $var setting from" >&2
        return 1
      fi
      continue
    fi
    line=$(grep -E "^${var}=" "$ops_env" || true)
    if [[ -n $line ]]; then
      ( umask 077; printf '%s\n' "$line" >> "$watch_env" )
      echo "Copied $var into $watch_env (value not shown)."
    fi
  done
  if ! { grep -q "^LINE_CHANNEL_ACCESS_TOKEN=" "$watch_env" && grep -q "^LINE_RECIPIENT_ID=" "$watch_env"; }; then
    echo "INSTALL_FAILED: no LINE settings for the watcher: LINE is its primary channel (put LINE_CHANNEL_ACCESS_TOKEN and LINE_RECIPIENT_ID in $ops_env or $watch_env)" >&2
    return 1
  fi
  if ! { grep -q "^TELEGRAM_BOT_TOKEN=" "$watch_env" && grep -q "^TELEGRAM_CHAT_ID=" "$watch_env"; }; then
    echo "WARNING: no Telegram settings: a LINE failure will not be sent anywhere else." >&2
  fi
  echo "$watch_env has $(wc -l < "$watch_env") lines; contents not shown."
}
