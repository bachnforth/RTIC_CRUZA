# Field startup order (T2 Cruza, QGC over the Pocket's backpack Wi-Fi)

## Passwords (ELRS defaults, all the same)
| Network | Password |
|---|---|
| The Pocket's TX backpack ("ExpressLRS TX Backpack ...") | `expresslrs` |
| The receiver's setup network ("ExpressLRS RX", only for firmware updates) | `expresslrs` |
| The Pocket module's setup network ("ExpressLRS TX", only for firmware updates) | `expresslrs` |

QGC link: UDP, local port 14550, server address `10.0.0.1:14555` (saved as "TW Cruza").

## Order of operations
1. **Before you leave a network with internet:** open QGC and the Plan view once so the map tiles and mission are cached. Joining the backpack drops the hotspot (one Wi-Fi card = one network at a time).
2. **Safety state:** propellers OFF for any bench work. Arm switch (channel 8) LOW. Throttle stick at zero. RTL switch (channel 5) off.
3. **Pocket on first.** Wait until the Lua screen shows the connection indicator once the aircraft is powered (step 5).
4. **Aircraft on the ground, flat and still, GPS facing the sky.**
5. **Connect the flight battery.** Then DO NOT touch or move the aircraft for 15 seconds (gyro calibration). The receiver LED goes solid when linked.
6. **Wait for GPS:** about 8+ satellites and a 3D fix. The BeeID's LED goes solid green with a fix.
7. **On the laptop, join the backpack network** (see "Which network is mine?"). Password `expresslrs`. Windows will say "No internet": stay connected. If it shows a 169.254.x.x address, run `ipconfig /renew` or `.\tools\connect-backpack.ps1`.
8. **QGC:** connect the "TW Cruza" UDP link (Application Settings > Comm Links > select > Connect). Wait for the parameter download; do not open config pages until it finishes.
9. **Prove it is YOUR aircraft:** flip the channel 7 mode switch and watch QGC's mode follow. If it does not, DISCONNECT QGC and try the other network. Never arm or send commands until it follows.
10. **Pre-arm checks:** no red messages in the message list, GPS healthy, home set, battery above 15 V. Gyro messages mean it was moved at startup: reboot, keep still.
11. **Arm only when ready to launch** (channel 8 up). Disarm (channel 8 down) after landing.
12. **Shutdown:** disarm, disconnect the battery, then turn the Pocket off. Reconnect the laptop to the hotspot.

## Which network is mine?
- The backpack's name has changed over time (217F95, A3144A, no suffix, D86872...). Other ELRS radios are nearby. Do not trust the name.
- Strongest signal is your best clue (the laptop is next to your Pocket), but the mode-switch test in step 9 is the proof.
- Do not join a network and send commands to it unless step 9 passes.
