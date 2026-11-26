# powermetrics

> Show CPU usage, wakeups, power and frequency statistics, and estimated power used by the CPU, GPU and other subsystems.
> Requires root privileges.
> More information: <https://keith.github.io/xcode-man-pages/powermetrics.1.html>.

- Show the default statistics every 5 seconds until interrupted:

`sudo powermetrics`

- Take a given number of samples at a given interval in milliseconds:

`sudo powermetrics -i {{1000}} -n {{5}}`

- Show CPU power and frequency information:

`sudo powermetrics -s cpu_power`

- Show battery discharge rate, charge level and cycle count:

`sudo powermetrics -s battery`

- Show the current thermal pressure:

`sudo powermetrics -s thermal`

- Show the energy impact of each process:

`sudo powermetrics --show-process-energy`

- Write the output to a file:

`sudo powermetrics -o {{path/to/file}}`
