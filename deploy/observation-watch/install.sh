#!/usr/bin/env bash
# Install the observation watcher (f-43) on the dev host (trading-dev, or fleet-standby-1 with WATCH_USER=ubuntu).  Idempotent.
#
#   sudo bash deploy/observation-watch/install.sh            # WATCH_USER defaults to ai001; on fleet-standby-1: sudo WATCH_USER=ubuntu bash ...
#
# - /opt/observation-watch/observation_watch.py : a copy of scripts/observation_watch.py (root-owned)
# - /etc/observation-watch/watch.env            : LINE_CHANNEL_ACCESS_TOKEN / LINE_RECIPIENT_ID (the primary channel) and
#                                                 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (the fallback), each copied from
#                                                 /etc/ops-notify/ops-notify.env when it is not in the file yet (root 0600);
#                                                 no value is ever printed
# - warn-only preflight (watch_preflight.sh): the five clones, A1 in known_hosts, ssh key mode; install goes on regardless
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

# shellcheck source=deploy/observation-watch/watch_preflight.sh
source "$SRC/deploy/observation-watch/watch_preflight.sh"
watch_preflight "$HOME_DIR" 161.33.186.220 oci_a1_key

install -d -m 755 /opt/observation-watch
install -o root -g root -m 755 "$SRC/scripts/observation_watch.py" /opt/observation-watch/observation_watch.py
install -d -m 700 /etc/observation-watch

WATCH_ENV=/etc/observation-watch/watch.env
# shellcheck source=deploy/observation-watch/watch_env.sh
source "$SRC/deploy/observation-watch/watch_env.sh"
ensure_watch_env /etc/ops-notify/ops-notify.env "$WATCH_ENV" || exit 1
chown root:root "$WATCH_ENV"; chmod 600 "$WATCH_ENV"

install -d -o "$WATCH_USER" -g "$WATCH_USER" -m 755 "$HOME_DIR/.local/state/observation-watch"
for unit in observation-watch.service observation-watch.timer; do
  sed "s/@WATCH_USER@/$WATCH_USER/g" "$SRC/deploy/observation-watch/$unit" > "/etc/systemd/system/$unit"
  chmod 644 "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now observation-watch.timer
echo "Installed. First run:  sudo systemctl start observation-watch.service ; read it:  python3 /opt/observation-watch/observation_watch.py report"
