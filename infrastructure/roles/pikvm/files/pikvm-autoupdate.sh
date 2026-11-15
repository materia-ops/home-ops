#!/bin/bash
# Managed by Ansible (infrastructure/roles/pikvm).
# pikvm-update --no-reboot exits 0 = already up to date, 100 = updated (reboot
# needed, / left rw), 101 = kvmd config invalid after the update (must NOT
# reboot); anything else is a failure that leaves / rw until the next reboot.
# The journal and /var/log are tmpfs, so every run is also recorded on the PST
# partition: /var/lib/kvmd/pst/data/autoupdate/{history,last-run}.log.
set -u

log=/tmp/pikvm-autoupdate.log
/usr/bin/pikvm-update --no-reboot >"$log" 2>&1
rc=$?
case $rc in
	0) result=up-to-date ;;
	100) result=updated ;;
	101) result=kvmd-config-invalid ;;
	*) result=failed ;;
esac
cat "$log"

# Expanded by the child shell, where kvmd-pstrun has set KVMD_PST_DATA.
# shellcheck disable=SC2016
RC=$rc RESULT=$result LOG=$log /usr/bin/kvmd-pstrun -- /bin/sh -c '
	d="$KVMD_PST_DATA/autoupdate"
	mkdir -p "$d"
	printf "%s rc=%s %s\n" "$(date -u +%FT%TZ)" "$RC" "$RESULT" >>"$d/history.log"
	tail -n 200 "$d/history.log" >"$d/history.tmp" && mv "$d/history.tmp" "$d/history.log"
	cp "$LOG" "$d/last-run.log"
' || echo "pikvm-autoupdate: could not write the PST run record" >&2

if [ "$rc" -eq 100 ]; then
	systemctl --no-block reboot
	exit 0
fi
exit "$rc"
