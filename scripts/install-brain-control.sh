#!/usr/bin/env bash
# Install the Mac brain-control launchd job: pure-logic modules, real I/O
# senders, the tick entry point, and the launchd plist that runs it every
# 30 seconds. Safe to re-run: it never overwrites a config, mode, key, or
# token that already exists.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="${HOME}"
BC_DIR="${HOME_DIR}/.brain-control"
LIB_DIR="${BC_DIR}/lib"
PKG_DIR="${LIB_DIR}/brain_control"
BRIDGE_DIR="${HOME_DIR}/.imsg-bridge"
GATE_PATH="${BRIDGE_DIR}/imsg-ssh-gate"
LAUNCH_AGENTS_DIR="${HOME_DIR}/Library/LaunchAgents"
PLIST_DEST="${LAUNCH_AGENTS_DIR}/com.assistant.brain-control.plist"
LABEL="com.assistant.brain-control"

echo "==> Step 1: creating ${BC_DIR}"
mkdir -p "${PKG_DIR}"
chmod 700 "${BC_DIR}"

echo "==> Step 2: copying brain_control package"
cp "${SCRIPT_DIR}/brain_control/"*.py "${PKG_DIR}/"

CONFIG_PATH="${BC_DIR}/config.json"
if [ ! -f "${CONFIG_PATH}" ]; then
  echo "==> Step 3: writing config.json template (edit the placeholder values before enabling failover)"
  cat > "${CONFIG_PATH}" <<CONFIGEOF
{
  "repo_dir": "${HOME_DIR}/workspace/assistant",
  "docker": "/usr/local/bin/docker",
  "lease_path": "${BRIDGE_DIR}/active-brain",
  "mode_path": "${BC_DIR}/mode",
  "state_path": "${BC_DIR}/state.json",
  "lock_path": "${BC_DIR}/tick.lock",
  "log_path": "${BC_DIR}/brain-control.log",
  "pc_health_url": "http://100.123.4.5:18789/healthz",
  "hooks_urls": {"pc": "http://100.123.4.5:18789", "mac": "http://127.0.0.1:18789"},
  "hooks_token_path": "${BC_DIR}/hooks-token",
  "syncthing_config": "${HOME_DIR}/Library/Application Support/Syncthing/config.xml",
  "syncthing_folder": "openclaw-workspace",
  "pc_device_name": "desktop-3p37btg",
  "reminders_dir": "${HOME_DIR}/workspace/assistant/data/openclaw/workspace/reminders",
  "env_path": "${HOME_DIR}/workspace/assistant/.env",
  "mark_handle_env": "MARK_IMESSAGE_HANDLE",
  "clock_ssh_key": "${BC_DIR}/clock_ed25519",
  "clock_known_hosts": "${BC_DIR}/known_hosts",
  "clock_ssh_target": "${USER}@127.0.0.1"
}
CONFIGEOF
  chmod 600 "${CONFIG_PATH}"
else
  echo "==> Step 3: config.json already exists, leaving it alone"
fi

MODE_PATH="${BC_DIR}/mode"
if [ ! -f "${MODE_PATH}" ]; then
  echo "off" > "${MODE_PATH}"
  chmod 600 "${MODE_PATH}"
  echo "    wrote ${MODE_PATH} = off"
else
  echo "    mode file already exists, leaving it alone"
fi

CLOCK_KEY="${BC_DIR}/clock_ed25519"
if [ ! -f "${CLOCK_KEY}" ]; then
  ssh-keygen -t ed25519 -N "" -C brain-control-clock -f "${CLOCK_KEY}" >/dev/null
  echo "    generated ${CLOCK_KEY}"
else
  echo "    clock key already exists, leaving it alone"
fi

KNOWN_HOSTS="${BC_DIR}/known_hosts"
if [ ! -f "${KNOWN_HOSTS}" ]; then
  HOST_KEY_PUB="/etc/ssh/ssh_host_ed25519_key.pub"
  if [ -f "${HOST_KEY_PUB}" ]; then
    HOST_KEY_LINE="$(awk '{print $1, $2}' "${HOST_KEY_PUB}")"
    echo "127.0.0.1 ${HOST_KEY_LINE}" > "${KNOWN_HOSTS}"
    chmod 600 "${KNOWN_HOSTS}"
    echo "    wrote ${KNOWN_HOSTS}"
  else
    echo "    WARNING: ${HOST_KEY_PUB} not found; skipping known_hosts (Remote Login may be off)."
  fi
else
  echo "    known_hosts already exists, leaving it alone"
fi

TOKEN_PATH="${BC_DIR}/hooks-token"
if [ ! -f "${TOKEN_PATH}" ]; then
  openssl rand -hex 32 > "${TOKEN_PATH}"
  chmod 600 "${TOKEN_PATH}"
  echo "    generated hooks-token"
else
  echo "    hooks-token already exists, leaving it alone"
fi

echo "==> Step 4: installing the ssh gate"
mkdir -p "${BRIDGE_DIR}"
chmod 700 "${BRIDGE_DIR}"
if [ -f "${GATE_PATH}" ]; then
  BACKUP_PATH="${GATE_PATH}.bak-$(date +%Y%m%d%H%M%S)"
  cp "${GATE_PATH}" "${BACKUP_PATH}"
  echo "    backed up existing gate to ${BACKUP_PATH}"
fi
cp "${SCRIPT_DIR}/imsg-ssh-gate.py" "${GATE_PATH}"
chmod 755 "${GATE_PATH}"

echo "==> Step 5: installing the launchd job"
mkdir -p "${LAUNCH_AGENTS_DIR}"
sed -e "s#__LIB__#${LIB_DIR}#g" -e "s#__HOME__#${HOME_DIR}#g" \
  "${SCRIPT_DIR}/brain-control.plist" > "${PLIST_DEST}"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DEST}"

echo "==> Step 6: next steps"
echo ""
echo "Add this line to this Mac's ~/.ssh/authorized_keys for the clock role"
echo "(fenced to send-only, loopback only):"
echo ""
echo "from=\"127.0.0.1,::1\",restrict,command=\"${HOME_DIR}/.imsg-bridge/imsg-ssh-gate --brain clock\" $(cat "${CLOCK_KEY}.pub")"
echo ""
echo "Remote Login must be on for this to work: System Settings > General >"
echo "Sharing > Remote Login."
echo ""
echo "brain-control is installed but mode is 'off' (no automatic failover yet)."
echo "Edit ${CONFIG_PATH} with the real PC health URL, hooks URLs, and Syncthing"
echo "device name, add the authorized_keys line above, then set mode to 'auto':"
echo ""
echo "  echo auto > ${MODE_PATH}"
echo ""
echo "The job ticks every 30 seconds. Logs: ${BC_DIR}/brain-control.log"
