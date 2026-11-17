#!/usr/bin/env bash
# worldserver preStop hook: give real players a timed in-game restart warning.
#
# Any orchestrated termination (image bump, config roll via Reloader, node
# drain) runs this BEFORE SIGTERM. If real players are online — AC's
# "Connected players" count excludes bots — it SOAPs
# `server restart <N>` against the pod's OWN worldserver, which broadcasts a
# countdown in-game and exits cleanly (full save) when it reaches zero. With
# nobody online (or SOAP unreachable/unparseable) it returns immediately and
# the normal SIGTERM save-and-stop proceeds at full speed.
#
# Emergency bypass: kubectl delete pod <ws-pod> --grace-period=1
#
# Deliberately NO `set -e`: any failure here must degrade to the plain
# SIGTERM path, never wedge the hook.
set -uo pipefail

# pod.terminationGracePeriodSeconds must exceed this + the hold margin below +
# save time: see the helmrelease comment.
WARN_SECONDS="${WARN_SECONDS:-900}"

soap() {
  curl -s --max-time 10 \
    -u "${SOAP_USERNAME}:${SOAP_PASSWORD}" \
    -H "Content-Type: text/xml" \
    --data-binary @- \
    "http://127.0.0.1:7878/" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">
  <SOAP-ENV:Body><ns1:executeCommand><command>$1</command></ns1:executeCommand></SOAP-ENV:Body>
</SOAP-ENV:Envelope>
EOF
}

info="$(soap "server info")" || { echo "preStop: SOAP unreachable — plain SIGTERM path"; exit 0; }
players="$(sed -n 's/.*Connected players: \([0-9]\{1,\}\).*/\1/p' <<< "${info}" | head -n1)"

if [ -z "${players}" ] || [ "${players}" -eq 0 ]; then
  echo "preStop: no real players online (parsed: '${players:-unparseable}') — immediate shutdown"
  exit 0
fi

echo "preStop: ${players} player(s) online — starting ${WARN_SECONDS}s in-game restart countdown"
soap "server restart ${WARN_SECONDS}"

# Hold the hook open: worldserver (PID 1) exits on its own at zero, which ends
# the container and this hook with it. After an in-game `server restart cancel`
# the hold expires and kubelet's SIGTERM does a normal graceful stop.
sleep $((WARN_SECONDS + 120))
echo "preStop: countdown window elapsed (cancelled in-game?) — releasing to SIGTERM"
exit 0
