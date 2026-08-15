# Moving the AI Brain to Oracle Cloud Always Free

Always Free gives you an Ampere A1 allocation — up to 4 OCPUs and 24 GB RAM —
that does not expire. The AI Brain peaks around **78 MB** and the image is
**466 MB**, so even a 1-core/6 GB slice is enormous overkill. It also never
sleeps, which Render's and Hugging Face's free tiers do.

The catch is that Oracle's console is genuinely unpleasant and the networking
has one trap that catches nearly everyone. Both are covered below.

Everything here has been built and tested; what could not be tested from this
machine is marked.

---

## What was verified before you start

| | |
|---|---|
| Image builds | 19 s, 466 MB, `linux/arm64` |
| Architecture | built on Apple Silicon = **aarch64**, the same as Ampere A1 |
| Container runs | healthy, as non-root user `brain` (uid 1000) |
| Installed packages | only the three declared: openai, sympy, numpy |
| Smoke test in container | **42/42 pass**, including the streaming answer |

Not verified from here: the Oracle instance itself. It needs your tenancy, and
creating the account is yours to do.

---

## 1. Create the instance

Oracle Cloud console → **Compute → Instances → Create instance**.

- **Image**: Oracle Linux 9 (or Ubuntu 22.04 — then swap `dnf` for `apt` in
  cloud-init)
- **Shape**: **Ampere → VM.Standard.A1.Flex**, 1 OCPU / 6 GB is plenty
  - if you see *"Out of host capacity"*, that is Oracle's chronic A1 shortage
    in popular regions, not a mistake on your side. Try another availability
    domain, or a different home region.
- **SSH keys**: upload your public key (`~/.ssh/id_ed25519.pub`)
- **Advanced options → Initialization script**: paste `deploy/cloud-init.yaml`

Note the **public IP** when it finishes.

## 2. Open the port — *both* places

This is the trap. Oracle requires two independent things, and the failure mode
of missing the second is a connection that hangs with no error anywhere.

**a. VCN security list** (console): Networking → Virtual Cloud Networks → your
VCN → Security Lists → Default → **Add Ingress Rule**

    Source 0.0.0.0/0   IP Protocol TCP   Destination Port 80  (and 443)

**b. The instance firewall.** Oracle Linux images ship with a `REJECT` rule
early in the INPUT chain, so the packet arrives and is dropped *on the box*.
The cloud-init above already does this, but if you skipped it:

```bash
sudo iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
sudo iptables-save | sudo tee /etc/sysconfig/iptables
```

If the site is unreachable, it is almost always (b).

## 3. Put the key on the box

```bash
ssh opc@<public-ip>
sudo sh -c 'echo DEEPSEEK_API_KEY=sk-... > /etc/ai-brain.env'
sudo chmod 600 /etc/ai-brain.env
```

Root-only, and read by systemd via `EnvironmentFile` rather than `Environment=`
— anything set the latter way shows up in `systemctl show`.

## 4. Ship it

From this directory:

```bash
./deploy/deploy-oracle.sh opc@<public-ip>
```

It builds for arm64, **runs the image locally and checks `/api/status` before
shipping anything**, streams the image over SSH (`docker save | gzip | ssh`),
restarts the service, and curls the public IP. No registry, no Docker Hub
account, and the bytes that were tested are the bytes that run.

First transfer moves a few hundred MB. Later ones reuse cached layers.

## 5. Verify

```bash
python3 tests/smoke_deployment.py http://<public-ip>
```

42 checks, with the numeric ones asserting closed forms — the 2/L convergence
rule, a singular matrix refusing to invert, power iteration finding 5 on
diag(5,1). A box can return 200 on every route while computing nonsense; these
would catch it.

## 6. TLS, once you have a domain

Caddy is configured in cloud-init and gets a certificate automatically:

```bash
sudo sed -i 's/^:80 {/brain.yourdomain.com {/' /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

The reverse proxy already sets `flush_interval -1` and a 10-minute timeout.
Both matter: answers stream as Server-Sent Events for minutes, and a default
30-second proxy timeout cuts every one of them off mid-sentence.

---

## Operating it

```bash
systemctl status ai-brain          # is it up
journalctl -u ai-brain -f          # logs
docker logs -f ai-brain            # the app's own output
sudo systemctl restart ai-brain    # after changing the key
```

The container has `--memory 1g` and `Restart=always`, so a runaway request
cannot take the box down and a crash comes back by itself.

## Cost

Zero, if you stay inside Always Free: A1 up to 4 OCPU / 24 GB, 200 GB block
storage, 10 TB/month egress. The one way to get charged is upgrading the
account to Pay As You Go and then exceeding the free allowances — a Free Tier
account cannot silently bill you, it just stops.

## Doing this for the other apps

The Quantum Professor is the same shape — stdlib HTTP server reading `$PORT`,
no database — so its Dockerfile is this one with the paths changed, and one box
can host several containers behind the same Caddy on different ports. Worth
proving with the AI Brain first, which is the plan.
