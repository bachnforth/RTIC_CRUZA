# TFWdrone receiver installation

This receiver accepts Cruza test traffic forwarded by the laptop gateway over Doodle Labs mesh. The laptop mesh source `10.223.58.11/32` is explicitly allowed.

Download **linktest.py** and **plan.json** from this folder, or download and extract [the complete receiver ZIP](../tfwdrone-receiver.zip). On GitHub, use the file download button or Raw; do not save the GitHub HTML page as Python.

Copy those two files into `~/linktest/` on TFWdrone. Verify the Pi has mesh address `10.223.53.30` and VPN interface address `100.100.0.6`. Python 3 is required; no extra Python packages are needed.

Run on TFWdrone:

```sh
mkdir -p ~/linktest-logs
cd ~/linktest
python3 linktest.py stop --role echo
nohup python3 linktest.py echo --name tfwdrone > ~/linktest-logs/echo-console.log 2>&1 < /dev/null &
```

The stop command affects only this tool's echo process. If you already have files in `~/linktest`, back them up before replacing them. This does not install a startup service or change aircraft services, routes, radios, or flight-controller settings.

Tell Bach when the receiver is running so he can initiate the round-trip test from Cruza through alien08. Leave it running until that test is finished. To stop afterward:

```sh
python3 ~/linktest/linktest.py stop --role echo
```

Logs are under `~/linktest-logs/`. The laptop forwards UDP `100.100.0.23:15711` to this receiver at `10.223.53.30:15700`. This is test data, not a video or MAVLink receiver.
