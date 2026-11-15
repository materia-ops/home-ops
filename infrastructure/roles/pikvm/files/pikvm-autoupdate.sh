#!/bin/bash
# Managed by Ansible (infrastructure/roles/pikvm).
# pikvm-update --no-reboot exits 0 = already up to date, 100 = updated (reboot
# needed, / left rw), 101 = kvmd config invalid after the update (must NOT
# reboot); anything else is a failure that leaves / rw until the next reboot.
# The journal is tmpfs, so each run is also recorded on the PST partition.
set -u

log=/run/pikvm-autoupdate.log
/usr/bin/pikvm-update --no-reboot >"$log" 2>&1
rc=$?
# pikvm-update checks kvmd's config only after installing something.
if [ "$rc" -eq 0 ] && ! /usr/bin/kvmd -m >/dev/null 2>&1; then
	rc=101
fi
case $rc in
	0) result=up-to-date ;;
	100) result=updated ;;
	101) result=kvmd-config-invalid ;;
	*) result=failed ;;
esac
cat "$log"

# Expanded by the child shell, where kvmd-pstrun has set KVMD_PST_DATA.
# shellcheck disable=SC2016
if ! RC=$rc RESULT=$result LOG=$log /usr/bin/kvmd-pstrun -- /bin/sh -c '
	d="$KVMD_PST_DATA/autoupdate"
	mkdir -p "$d"
	printf "%s rc=%s %s\n" "$(date -u +%FT%TZ)" "$RC" "$RESULT" >>"$d/history.log"
	tail -n 200 "$d/history.log" >"$d/history.tmp" && mv "$d/history.tmp" "$d/history.log"
	cp "$LOG" "$d/last-run.log"
'; then
	# kvmd-pstrun loads kvmd's config, so it fails exactly when that is broken;
	# a failed pikvm-update leaves / rw, so fall back to the root filesystem.
	printf "%s rc=%s %s (PST write failed)\n" "$(date -u +%FT%TZ)" "$rc" "$result" \
		>>/var/lib/pikvm-autoupdate.log 2>/dev/null ||
		echo "pikvm-autoupdate: could not record this run" >&2
fi

if [ "$rc" -eq 100 ]; then
	systemctl --no-block reboot
	exit 0
fi
exit "$rc"
