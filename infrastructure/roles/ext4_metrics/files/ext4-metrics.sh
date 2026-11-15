#!/bin/sh
# Managed by Ansible (infrastructure/roles/ext4_metrics).
# Writes ext4's per-filesystem superblock counters for node_exporter's textfile
# collector. errors_count survives reboots until e2fsck clears it, so it is the
# one failing-SD-card signal an SD card (no SMART) still gives.
set -eu

dir=$1
out="$dir/ext4.prom"
tmp="$out.tmp"

# One metric family per call: name, type, help, sysfs file, multiplier.
family() {
	printf '# HELP %s %s\n# TYPE %s %s\n' "$1" "$3" "$1" "$2"
	for fs in /sys/fs/ext4/*/; do
		[ -r "$fs$4" ] || continue
		printf '%s{device="%s"} %s\n' "$1" "$(basename "$fs")" "$(($(cat "$fs$4") * $5))"
	done
}

{
	family ext4_errors_total counter \
		"Errors recorded in the ext4 superblock since the last fsck." errors_count 1
	family ext4_last_error_time_seconds gauge \
		"When ext4 last recorded an error (0 = never)." last_error_time 1
	family ext4_lifetime_write_bytes_total counter \
		"Bytes written to the filesystem over its lifetime." lifetime_write_kbytes 1024
} >"$tmp"
mv "$tmp" "$out"
