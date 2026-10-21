# Automatic Cruza video startup

The owner requested video startup after boot on October 15, 2026, following a
confirmed IMX500 picture in Android QGroundControl. This supersedes earlier
notes describing a manually started, 120-second video test.

`cruza-video.service` supports opt-in startup through `multi-user.target` and
waits for network startup and Tailscale service ordering. It has no dependency
on the mesh, gateway, receiver, or MAVLink router. Enabling video does not
make flight-control services depend on video. The stream runs as `ebach`,
with reduced scheduling priority and bounded failure retries.

The opt-in installer sets only `video_max_seconds` to `0` in the existing
configuration. The current economy profile is 640x480, 15 FPS, 300 kbps,
directed to the configured Android VPN IP on UDP port 5600. Other settings
are preserved. Nonzero duration limits of 1–7200 seconds remain supported.

Video continues while QGroundControl is closed or the phone is unavailable.
At 300 kbps, encoded video alone uses approximately 135 MB/hour when carried
over LTE; network overhead adds to this. There is no viewer detector.

## Deployment evidence — October 15, 2026

Installed on TFWCRUZA with original files saved under
`/var/backups/cruza/video-autostart-20261015T205057Z`. Five unit tests passed on
both the laptop and Pi; shell syntax and systemd unit validation passed.
The first deployment rolled back because resetting the failed state of an
unloaded service returned an error; the installer now only resets a failed unit.
The corrected deployment reports video enabled and running, with the MAVLink
router still active. Actual automatic startup remains unverified until the
next owner-authorized reboot or power cycle.

## Deploy

Place `cruza.py`, `enable-video-autostart.sh`, and
`systemd/cruza-video.service` together on the Pi, preserving their paths, then run:

```bash
sudo bash enable-video-autostart.sh
```

The installer validates the configuration and systemd unit, backs up the
original code, configuration, unit and service states under
`/var/backups/cruza/video-autostart-TIMESTAMP`, enables video and starts it.
It rolls back on deployment errors. It does not restart MAVLink routing,
reboot the Pi, or change aircraft parameters.

## Operation and verification

```bash
systemctl is-enabled cruza-video
systemctl is-active cruza-video
journalctl -b -u cruza-video --no-pager -n 30
sudo systemctl stop cruza-video       # Stop now; boot startup remains enabled.
sudo systemctl disable --now cruza-video  # Stop and disable future boot startup.
sudo systemctl enable --now cruza-video   # Enable boot startup and start now.
```

In Android QGroundControl use UDP h.264, receiving port 5600. Confirm the picture
persists beyond the old 120-second limit. Boot startup requires checking again
after the next owner-authorized reboot or power cycle; enabling a unit alone
does not prove a successful post-boot stream.

Failure retries are three starts per five minutes, with a 30-second delay.
After correcting a persistent camera/network fault, use
`sudo systemctl reset-failed cruza-video` and `sudo systemctl start cruza-video`.

## Restore original files

Use the exact backup path printed by the installer:

```bash
backup=/var/backups/cruza/video-autostart-TIMESTAMP
sudo systemctl disable --now cruza-video
sudo cp -a "$backup/cruza.py" /opt/cruza/cruza.py
sudo cp -a "$backup/config.json" /etc/cruza/config.json
sudo cp -a "$backup/cruza-video.service" /etc/systemd/system/cruza-video.service
sudo systemctl daemon-reload
```

Restore the enabled/active service states recorded in `enabled-state.txt` and
`active-state.txt` if they differed. Other companion services are left running.
