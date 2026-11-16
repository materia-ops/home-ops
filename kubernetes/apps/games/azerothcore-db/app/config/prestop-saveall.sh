#!/usr/bin/env bash
# mysqld preStop: before the DB receives SIGTERM, ask the worldserver to flush
# all in-memory character state (`saveall`).
# Otherwise an orchestrated DB roll (image update, node drain, reschedule)
# rewinds the realm to the last periodic save (PlayerSaveInterval is 15 min):
# the worldserver drops its DB connection and its SOAP liveness probe restarts it.
#
# Best-effort by design: if the worldserver is down or hung there is nothing
# to save — log and exit 0 so the DB shutdown is never blocked.
set -uo pipefail

resp="$(curl -s --max-time 20 \
  -u "${SOAP_USERNAME}:${SOAP_PASSWORD}" \
  -H "Content-Type: text/xml" \
  --data-binary @- \
  "http://azerothcore-soap.games.svc.cluster.local:7878/" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">
  <SOAP-ENV:Body><ns1:executeCommand><command>saveall</command></ns1:executeCommand></SOAP-ENV:Body>
</SOAP-ENV:Envelope>
EOF
)" || { echo "prestop: SOAP saveall failed (worldserver down?) — proceeding with DB shutdown"; exit 0; }

echo "prestop: saveall response: ${resp}"

# saveall queues the writes on the worldserver's async DB pipeline; give them
# time to commit before mysqld stops accepting work. Budgeted inside the
# pod's terminationGracePeriodSeconds (120s).
sleep 15
exit 0
