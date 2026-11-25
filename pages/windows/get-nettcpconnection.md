# Get-NetTCPConnection

> Get TCP connections, with their local and remote addresses, ports, state and owning process.
> Note: This command can only be used through PowerShell.
> See also: `netstat`.
> More information: <https://learn.microsoft.com/powershell/module/nettcpip/get-nettcpconnection>.

- List all TCP connections:

`Get-NetTCPConnection`

- List established connections:

`Get-NetTCPConnection -State Established`

- List the connections of a process by its ID:

`Get-NetTCPConnection -OwningProcess {{18948}}`

- List the connections on a local port:

`Get-NetTCPConnection -LocalPort {{port}}`
