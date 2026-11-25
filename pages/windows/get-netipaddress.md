# Get-NetIPAddress

> Get the IP address configuration of the network interfaces.
> Note: This command can only be used through PowerShell.
> See also: `ipconfig`.
> More information: <https://learn.microsoft.com/powershell/module/nettcpip/get-netipaddress>.

- Show all IP addresses as a table:

`Get-NetIPAddress | Format-Table`

- Show IPv6 addresses only:

`Get-NetIPAddress -AddressFamily IPv6`

- Show the IP addresses of one interface by its index:

`Get-NetIPAddress -InterfaceIndex {{12}}`

- Show all IP addresses sorted by interface:

`Get-NetIPAddress | Sort-Object -Property InterfaceIndex | Format-Table`
