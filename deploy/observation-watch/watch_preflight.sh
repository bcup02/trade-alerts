#!/usr/bin/env bash
# Warn-only checks for a NEW host before the observation watcher's first run (sourced by install.sh; tested on its own).
#
#   watch_preflight <home-dir> <a1-host> <ssh-key-name>
#
# Prints a WARNING line for each thing the watcher needs that is missing; never fails, never prints a secret:
#   - the five clones it reads (registry clone + four strategy clones under <home-dir>); the unit skips missing ones,
#     so the registry checks would report errors instead of results;
#   - A1's host key in known_hosts (the watcher ssh's with StrictHostKeyChecking=yes, so an unknown host fails);
#   - the ssh key's permissions (must not be group/world readable).
# Returns the number of warnings in WATCH_PREFLIGHT_WARNINGS.

watch_preflight() {
  local home=$1 a1=$2 keyname=$3 repo kh found=no mode
  WATCH_PREFLIGHT_WARNINGS=0
  for repo in trade-alerts ed-seykota-systematic-trend-following mexc-4h-momentum-trailing-stop my-crypto-bot btc-bull-market-competition; do
    if [[ ! -d $home/$repo/.git ]]; then
      echo "WARNING: no clone $home/$repo (the watcher's registry/strategy checks will report errors until it exists)." >&2
      WATCH_PREFLIGHT_WARNINGS=$((WATCH_PREFLIGHT_WARNINGS + 1))
    fi
  done
  for kh in "$home/.ssh/known_hosts" /etc/ssh/ssh_known_hosts; do
    if [[ -r $kh ]] && ssh-keygen -F "$a1" -f "$kh" >/dev/null 2>&1; then found=yes; fi
  done
  if [[ $found == no ]]; then
    echo "WARNING: $a1 is not in known_hosts (the watcher uses StrictHostKeyChecking=yes, so every A1 read fails until the host key is added)." >&2
    WATCH_PREFLIGHT_WARNINGS=$((WATCH_PREFLIGHT_WARNINGS + 1))
  fi
  if [[ -f $home/.ssh/$keyname ]]; then
    # install.sh runs with set -e: a failing stat must become a warning, never end the install.
    if ! mode=$(stat -c '%a' "$home/.ssh/$keyname" 2>/dev/null) || [[ ! $mode =~ ^[0-7]{3,4}$ ]]; then
      echo "WARNING: cannot read the mode of $home/.ssh/$keyname (is it readable? ssh needs mode 600)." >&2
      WATCH_PREFLIGHT_WARNINGS=$((WATCH_PREFLIGHT_WARNINGS + 1))
    elif (( 8#$mode & 8#077 )); then
      echo "WARNING: $home/.ssh/$keyname has mode $mode (ssh refuses keys readable by group/others; use 600)." >&2
      WATCH_PREFLIGHT_WARNINGS=$((WATCH_PREFLIGHT_WARNINGS + 1))
    fi
  fi
  echo "Preflight: $WATCH_PREFLIGHT_WARNINGS warning(s)."
  return 0
}
