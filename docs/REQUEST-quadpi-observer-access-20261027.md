# QuadPi: two things, ~5 minutes — SSH key, and one file

From: jbrascom (`alien03`, tailnet `100.100.0.29`)
Date: 27 Oct 2026
Re: QuadPi only. **Cruza is solved** — since the 23 Oct reflash it accepts this key as
`jbrascom` and is working. This is the last piece.

**If you are busy this morning, skip to "If you cannot get to it" at the bottom — we are
not blocked, and I would rather you not rush this.**

---

## The key

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJRYJxUuXPcAfTjtpKvdCoPop1McHjhF3czGxNbyN//q windows-claude-to-pi
```

Fingerprint: `SHA256:4/G3uPJVNgWu1/nLxa1GDlVZWAKXWemg0Nc9iIufPRc`

Same key you authorized on 21 Oct. It is the same one the Cruza and the TFW drone both accept
today, so the key itself is known good.

## Where it has to go

QuadPi is up right now and I can reach it on the tailnet at `100.100.0.10`
(`10.223.79.20` on the mesh is down from here — our Alfa is off the Doodle SSID this morning,
that one is on me).

The dashboard connects **as `ebach`**, because that is how QuadPi was provisioned. So the key
needs to be in `ebach`'s file:

```sh
install -d -m 700 ~/.ssh
printf '%s\n' 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJRYJxUuXPcAfTjtpKvdCoPop1McHjhF3czGxNbyN//q windows-claude-to-pi' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
chown -R ebach:ebach ~/.ssh
```

If you would rather we came in as our own account, say so and make it `jbrascom` instead — it
is a one-line change on my side. I have no preference.

## What I measured this morning, so you are not debugging blind

One clean attempt per account, a few minutes ago. I did not leave anything retrying.

```
debug1: compat_banner: match: OpenSSH_10.0p2 Debian-7+deb13u4
debug1: Offering public key: id_ed25519_pi ED25519 SHA256:4/G3uPJVNgWu1/nLxa1GDlVZWAKXWemg0Nc9iIufPRc
debug1: Authentications that can continue: publickey,password
ebach@100.100.0.10: Permission denied (publickey,password).
```

Identical for `jbrascom@100.100.0.10`.

Two things that rules out, compared to 21 Oct:

- **Not fail2ban and not `MaxStartups`.** The connection completes, we exchange keys, sshd
  offers `publickey,password` and reads our offer. On 21 Oct we were getting
  `kex_exchange_identification: read: Connection reset`, which is a drop *before* auth. That
  has cleared — so whatever ban or throttle was in play has expired.
- **Not the network, and not the key.** sshd sees the right fingerprint and declines it.

So it is down to the authorized_keys file sshd actually reads for that account. Which is
consistent with QuadPi being on Debian 13 now — if it was reimaged at some point after
21 Oct, anything you added then is simply gone, and the block above is all that is needed.

### If it still fails after adding it

Then it is almost certainly permissions — sshd silently ignores `authorized_keys` when the home
directory or the file is too loose, and tells the client nothing. This prints modes and
fingerprints only, never key material:

```sh
ACCT=ebach
hostname; id "$ACCT"
sudo ls -ld "/home/$ACCT" "/home/$ACCT/.ssh" "/home/$ACCT/.ssh/authorized_keys"
sudo ssh-keygen -lf "/home/$ACCT/.ssh/authorized_keys"
sudo sshd -T | grep -Ei 'authorizedkeysfile|pubkeyauthentication|allowusers|denyusers|allowgroups'
```

And the one that ends the conversation — start it, tell me, and I will make a single attempt
on cue:

```sh
sudo journalctl -u ssh -f
```

A permissions refusal appears there verbatim, e.g.
`Authentication refused: bad ownership or modes for file /home/ebach/.ssh/authorized_keys`.

---

## The second thing, while you are in there

We are testing whether the Cruza, the TFW drone and QuadPi can share geolocated detections —
one aircraft spots something, another independently confirms it is in the same place. QuadPi's
part needs one read-only file:

**Heads up: the file is not on `main`.** It lives on `swarm-shared-picture` (and on
`cruza-quad-link-test`, where it has been since the ATR work). Checking out `main` will
come up empty.

```sh
cd RTIC_CRUZA
git fetch origin && git checkout swarm-shared-picture
sha256sum companion/observe-tap.py
# expect 695441dd305a71c63d8c8d4701f3c11891ca5c120d09f6bf5b88c31eb0cc7035
sudo install -m 644 companion/observe-tap.py /opt/cruza-observe-tap.py
```

That checksum is the committed file's, so you can verify before and after the install.

**What it does and does not do.** It binds one loopback UDP port (15621), reads small JSON
detection records, and writes them to its own stdout for the dashboard to read over SSH. No
camera access, no serial port, no MAVLink, no route, firewall, service or parameter change, and
it sends nothing back to the aircraft. It is Python standard library only, it exits on its own
when idle, and nothing starts it except the dashboard asking for it over SSH. There is no
systemd unit to install and nothing is enabled.

You do **not** need `deploy-observe.sh` — that one installs the IMX500 detector and will refuse
on QuadPi anyway, since QuadPi has an ordinary camera. Just the one file.

---

## If you cannot get to it

We will fly the test today as **Cruza + TFW drone**, which both already work with this key. That
still measures everything that matters — two aircraft independently placing the same object, and
how far apart they put it. QuadPi would make it three platforms instead of two, which is better,
but it is not the difference between a result and no result.

So: whenever suits you. Nothing is retrying against QuadPi in the meantime.

Thanks —
jbrascom
