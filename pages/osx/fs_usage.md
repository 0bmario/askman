# fs_usage

> Report system calls and page faults related to filesystem activity in real time.
> Requires root privileges.
> More information: <https://keith.github.io/xcode-man-pages/fs_usage.1.html>.

- Show filesystem activity of all processes:

`sudo fs_usage`

- Show filesystem-related activity of all processes with a given name, in wide output:

`sudo fs_usage -w -f filesys {{process_name}}`

- Show only network-related events:

`sudo fs_usage -f network`

- Show only disk I/O events:

`sudo fs_usage -f diskio`

- Show only exec and spawn events:

`sudo fs_usage -f exec`

- Stop after a number of seconds:

`sudo fs_usage -t {{seconds}}`

- Exclude a process from the output:

`sudo fs_usage -e {{process_name}}`
