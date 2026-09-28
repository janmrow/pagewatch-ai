# Ubuntu/systemd deployment

This is a manual deployment for a Mikrus 2.1 running Ubuntu. Pagewatch runs once per timer event and exits; it is not a daemon. The checked-out code and virtual environment live in `/opt/pagewatch`, watch configuration and credentials in `/etc/pagewatch`, and persistent baselines in `/var/lib/pagewatch`.

The timer runs at 08:00, 12:00, and 16:00 in `Europe/Warsaw`, regardless of the server's local timezone. `Persistent=true` causes one catch-up run when a missed timer is started again; it does not replay every missed event. Do not enable the timer until the manual run below succeeds.

## Prepare the host

Run these steps as an administrator with `sudo`. Check that the host has systemd, enough free disk space, and Python 3.11 or newer. Install Git, a supported Python interpreter, its `venv` module, CA certificates, and [uv](https://docs.astral.sh/uv/getting-started/installation/) using the Ubuntu and uv instructions appropriate to the installed release. Ubuntu's `/usr/bin/python3` must satisfy the project's Python requirement before the command below is run.

```sh
python3 --version
systemctl --version
uv --version
df -h /opt /var/lib
sudo useradd --system --home-dir /var/lib/pagewatch --no-create-home --shell /usr/sbin/nologin pagewatch
sudo git clone https://github.com/janmrow/pagewatch-ai.git /opt/pagewatch
sudo git -C /opt/pagewatch checkout <reviewed-commit>
sudo "$(command -v uv)" sync --directory /opt/pagewatch --locked --no-dev --python /usr/bin/python3
```

Use the reviewed PR merge commit or another known commit for `<reviewed-commit>`. `/opt/pagewatch` and `.venv` should remain owned by root and readable by `pagewatch`; do not give the service account write access to application code. The service runs the installed executable directly and does not need uv at runtime.

## Configure watches and credentials

```sh
sudo install -d -o root -g pagewatch -m 0750 /etc/pagewatch
sudo install -o root -g pagewatch -m 0640 /dev/null /etc/pagewatch/watches.toml
sudo install -o root -g root -m 0600 /dev/null /etc/pagewatch/pagewatch.env
sudoedit /etc/pagewatch/watches.toml
sudoedit /etc/pagewatch/pagewatch.env
```

Put `[[watches]]` entries in `watches.toml` as shown in the [README](../README.md#run-configured-watches). Use a stable, unique ID for each URL and selector; a state file cannot be reused for a different URL or selector.

Put these assignments in `pagewatch.env`, with real values supplied on the VPS:

```text
PAGEWATCH_LLM_URL=https://your-provider.example/v1/chat/completions
PAGEWATCH_LLM_API_KEY=replace-me
PAGEWATCH_LLM_MODEL=replace-me
PAGEWATCH_SMTP_HOST=smtp.example.com
PAGEWATCH_SMTP_PORT=587
PAGEWATCH_SMTP_USERNAME=replace-me
PAGEWATCH_SMTP_PASSWORD=replace-me
PAGEWATCH_MAIL_FROM=sender@example.com
PAGEWATCH_MAIL_TO=recipient@example.com
```

This file uses systemd `EnvironmentFile=` syntax: one `NAME=value` assignment per line, without `export`. The system service manager reads the root-only file and passes the variables to the unprivileged process. Keep the actual file and backups out of Git. Check outbound HTTPS access to monitored pages and the Chat Completions endpoint, plus outbound access to the SMTP STARTTLS port; the service needs no inbound port.

`StateDirectory=pagewatch` creates `/var/lib/pagewatch` for the `pagewatch` user when the service starts. Its mode is `0700`. Do not delete this directory during updates: it contains the handled baselines and any pending change awaiting classification or notification.

## Install and check the units

```sh
sudo install -o root -g root -m 0644 /opt/pagewatch/deploy/systemd/pagewatch.service /etc/systemd/system/pagewatch.service
sudo install -o root -g root -m 0644 /opt/pagewatch/deploy/systemd/pagewatch.timer /etc/systemd/system/pagewatch.timer
sudo systemd-analyze verify /etc/systemd/system/pagewatch.service /etc/systemd/system/pagewatch.timer
systemd-analyze calendar '*-*-* 08,12,16:00:00 Europe/Warsaw' --iterations=3
sudo systemctl daemon-reload
sudo systemctl start pagewatch.service
sudo systemctl status pagewatch.service --no-pager
sudo journalctl -u pagewatch.service -n 100 --no-pager
```

The first successful run establishes baselines and sends no email. `Type=oneshot` normally shows as inactive after successful completion. Check the journal for per-watch INFO events and for any ERROR event; an unsuccessful watch makes the service exit nonzero. The service account reads `watches.toml` directly; systemd reads the root-only environment file. The service account must be able to write its state directory. If a unit security setting fails inside the Mikrus container, record the exact journal error before changing the unit.

To exercise the complete path, use a controlled watch whose page can be changed after its first baseline. Run the service again and confirm the classification log, a relevant email if appropriate, and an advanced state file. A first run or an unchanged page cannot verify LLM or SMTP delivery. Do not place page text or credentials in the journal or public issue reports.

After the manual run succeeds, enable the schedule and inspect its next triggers:

```sh
sudo systemctl enable --now pagewatch.timer
systemctl list-timers --all pagewatch.timer
sudo journalctl -u pagewatch.service --since today --no-pager
```

Observe several scheduled cycles before adding automated deployment. `systemctl list-timers` shows timer triggers; `journalctl` and the service result show whether each run succeeded. A failed run is retried at the next scheduled cycle after the underlying problem is fixed.

## Update or pause

Stop the timer before changing the installed code or units. Keep a backup of `/var/lib/pagewatch` and the private files in `/etc/pagewatch` in a protected location.

```sh
sudo systemctl stop pagewatch.timer
sudo git -C /opt/pagewatch fetch origin
sudo git -C /opt/pagewatch checkout <reviewed-commit>
sudo "$(command -v uv)" sync --directory /opt/pagewatch --locked --no-dev --python /usr/bin/python3
sudo install -o root -g root -m 0644 /opt/pagewatch/deploy/systemd/pagewatch.service /etc/systemd/system/pagewatch.service
sudo install -o root -g root -m 0644 /opt/pagewatch/deploy/systemd/pagewatch.timer /etc/systemd/system/pagewatch.timer
sudo systemctl daemon-reload
sudo systemctl start pagewatch.service
sudo systemctl start pagewatch.timer
```

Use `sudo systemctl disable --now pagewatch.timer` to pause scheduled runs indefinitely. It leaves baselines untouched.
