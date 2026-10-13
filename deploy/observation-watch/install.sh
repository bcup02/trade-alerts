#!/usr/bin/env bash
# Install the observation watcher (f-43) on the dev host.  Idempotent.
#
#   sudo bash deploy/observation-watch/install.sh            # WATCH_USER defaults to ai001
#
# - /opt/observation-watch/observation_watch.py : a copy of scripts/observation_watch.py (root-owned)
# - /etc/observation-watch/watch.env            : TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID only, copied from
#                                                 /etc/ops-notify/ops-notify.env the first time (root 0600); the token is
#                                                 never printed
# - observation-watch.service / .timer          : every 30 minutes, runs as WATCH_USER (needs its ssh key to A1 and sudo)
set -euo pipefail

die() { echo "INSTALL_FAILED: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "run with sudo"

WATCH_USER=${WATCH_USER:-ai001}
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
id "$WATCH_USER" >/dev/null 2>&1 || die "no such user $WATCH_USER"
[[ -f $SRC/scripts/observation_watch.py ]] || die "missing $SRC/scripts/observation_watch.py"
HOME_DIR=$(getent passwd "$WATCH_USER" | cut -d: -f6)
[[ -f $HOME_DIR/.ssh/oci_a1_key ]] || die "$WATCH_USER has no ~/.ssh/oci_a1_key (read access to A1)"

install -d -m 755 /opt/observation-watch
install -o root -g root -m 755 "$SRC/scripts/observation_watch.py" /opt/observation-watch/observation_watch.py
install -d -m 700 /etc/observation-watch

if [[ ! -f /etc/observation-watch/watch.env ]]; then
  [[ -r /etc/ops-notify/ops-notify.env ]] || die "no /etc/ops-notify/ops-notify.env to copy the Telegram settings from"
  ( umask 077; grep -E '^(TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=' /etc/ops-notify/ops-notify.env > /etc/observation-watch/watch.env ) \
    || die "ops-notify.env has no TELEGRAM_* settings"
  chown root:root /etc/observation-watch/watch.env; chmod 600 /etc/observation-watch/watch.env
  echo "Created /etc/observation-watch/watch.env ($(wc -l < /etc/observation-watch/watch.env) lines; contents not shown)."
fi

install -d -o "$WATCH_USER" -g "$WATCH_USER" -m 755 "$HOME_DIR/.local/state/observation-watch"
for unit in observation-watch.service observation-watch.timer; do
  sed "s/@WATCH_USER@/$WATCH_USER/g" "$SRC/deploy/observation-watch/$unit" > "/etc/systemd/system/$unit"
  chmod 644 "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now observation-watch.timer
echo "Installed. First run:  sudo systemctl start observation-watch.service ; read it:  python3 /opt/observation-watch/observation_watch.py report"
