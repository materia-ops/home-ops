"""Which keys of a wanted FTL config both differ from the live one and restart FTL."""


def _walk(wanted, live, detailed, path, out):
    for key, want in wanted.items():
        here = path + [str(key)]
        have = live.get(key) if isinstance(live, dict) else None
        meta = detailed.get(key) if isinstance(detailed, dict) else None
        if isinstance(want, dict):
            _walk(want, have, meta, here, out)
        elif want != have:
            flags = meta.get("flags") if isinstance(meta, dict) else None
            # An unknown key counts as restarting: waiting needlessly beats racing a restart.
            if not isinstance(flags, dict) or flags.get("restart_dnsmasq", True):
                out.append(".".join(here))


def ftl_restart_keys(wanted, live, detailed):
    """Dotted names of the changed keys that /api/config?detailed=true flags restart_dnsmasq."""
    out = []
    _walk(wanted, live, detailed, [], out)
    return out


class FilterModule:
    def filters(self):
        return {"ftl_restart_keys": ftl_restart_keys}
