# proton-mail-bridge-relay

In-cluster SMTP for app notifications, backed by Proton Mail — no Gmail.

```
app ──:25, no auth, no TLS──▶ postfix ──:1025 + auth + STARTTLS──▶ bridge ──▶ Proton
```

One pod, two containers: **Postfix** (the relay apps talk to) and **Proton Mail
Bridge** (authenticates to Proton). Apps point at a single plain endpoint:

```
smtp://proton-mail-bridge-relay.default.svc.cluster.local:25
```

No username, no password, no TLS on the app side — Postfix holds the only
credentials and terminates STARTTLS to Bridge.

## Prerequisites

- A **paid Proton plan** (Mail Plus / Unlimited / Business). Bridge does not work
  on free accounts.
- A 1Password item named **`proton-mail-bridge`** (the ExternalSecret reads from
  it). Leave the credential fields blank for now — they're generated in step 3.

## First-time setup

These steps are **manual and one-off** — Bridge's login is interactive and its
keychain is not reproducible from Git.

### 1. Deploy

Already wired into `kubernetes/apps/default/kustomization.yaml`. Commit and let
Flux reconcile. The `bridge` container will be running but **not logged in** yet,
so Postfix can't relay until step 3–4.

### 2. Exec into Bridge

```sh
kubectl -n default exec -it deploy/proton-mail-bridge-relay -c bridge -- /bin/sh
```

### 3. Log in and grab the generated credentials

```sh
pkill bridge          # stop the auto-started instance
/usr/bin/bridge --cli
>>> login             # enter Proton email + password + 2FA
>>> info              # copy the SMTP username + password it prints
>>> exit
```

Bridge generates its **own** SMTP username/password (not your Proton login).
These are what Postfix uses upstream. The encrypted keychain is written to the
kopiur-backed PVC mounted at `/root`, so it survives pod restarts.

### 4. Store the credentials and refresh

Put the values from `info` into the **`proton-mail-bridge`** 1Password item:

| 1Password field    | Value from `bridge info` |
| ------------------ | ------------------------ |
| `BRIDGE_SMTP_USER` | SMTP username            |
| `BRIDGE_SMTP_PASS` | SMTP password            |

The ExternalSecret maps these to `RELAYHOST_USERNAME` / `RELAYHOST_PASSWORD` in
`proton-mail-bridge-relay-secret`.

> **Force a secret sync after editing 1Password.** The ExternalSecret only polls
> on its refresh interval, so a `force-sync` annotation pulls the new values
> immediately. (Reloader then restarts Postfix automatically on the secret change.)
>
> ```sh
> kubectl -n default annotate externalsecret proton-mail-bridge-relay \
>   force-sync="$(date +%s)" --overwrite
> ```
>
> Confirm both keys are populated:
>
> ```sh
> kubectl -n default get secret proton-mail-bridge-relay-secret \
>   -o go-template='{{range $k,$v := .data}}{{$k}}={{if gt (len $v) 0}}<set>{{else}}<EMPTY>{{end}}{{"\n"}}{{end}}'
> ```

If Reloader doesn't bounce it, restart manually so Postfix picks up the creds:

```sh
kubectl -n default rollout restart deploy/proton-mail-bridge-relay
```

> **Note:** the Bridge SMTP password is **regenerated whenever the vault is reset**
> (fresh login / re-created PVC). After any re-login, re-run `info`, update the two
> 1Password fields, and force-sync again as above.

### 5. Test

Send via the relay using Python's stdlib (no package install needed — `swaks` is
not in Alpine's default repos):

```sh
kubectl -n default run smtp-test --rm -it --restart=Never --image=python:3-alpine -- \
  python -c 'import smtplib; s=smtplib.SMTP("proton-mail-bridge-relay.default.svc",25,timeout=20); s.set_debuglevel(1); s.sendmail("noreply@materia.wtf",["you@materia.wtf"],"Subject: relay test\n\nit works"); s.quit(); print("SENT OK")'
```

`250 ... queued as ...` means Postfix accepted it. Then confirm the
Postfix→Bridge→Proton hop actually delivered:

```sh
kubectl -n default logs deploy/proton-mail-bridge-relay -c postfix --tail=30 \
  | grep -Ei "to=<|status=|relay=|said:"
```

`status=sent` = success (message lands in your Proton inbox). `status=deferred
(... 127.0.0.1:1025: Connection refused)` means Bridge isn't listening on the
expected port — see Gotchas.

## Pointing apps at it

Configure each app's SMTP settings as:

| Setting     | Value                                                  |
| ----------- | ------------------------------------------------------ |
| Host        | `proton-mail-bridge-relay.default.svc.cluster.local`   |
| Port        | `25`                                                   |
| Encryption  | None                                                   |
| Username    | _(leave blank)_                                        |
| Password    | _(leave blank)_                                        |
| From / Sender | an address under `materia.wtf`                       |

The relay only accepts connections from the cluster pod network
(`10.42.0.0/16`) and only relays mail `From` `materia.wtf` — see
`ALLOWED_SENDER_DOMAINS` / `POSTFIX_mynetworks` in `app/helmrelease.yaml`.
