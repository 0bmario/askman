# Get-Service

> Get the services on the computer, with their status.
> Note: This command can only be used through PowerShell.
> See also: `sc`, `Restart-Service`.
> More information: <https://learn.microsoft.com/powershell/module/microsoft.powershell.management/get-service>.

- List all services:

`Get-Service`

- Get services whose name begins with a string:

`Get-Service "{{wmi*}}"`

- Get services whose display name contains a string:

`Get-Service -DisplayName "*{{network}}*"`

- List services that are running:

`Get-Service | Where-Object {$_.Status -eq "Running"}`

- Sort services by status:

`Get-Service "{{s*}}" | Sort-Object Status`

- Get the services a service depends on:

`Get-Service "{{WinRM}}" -RequiredServices`
