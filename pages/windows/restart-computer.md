# Restart-Computer

> Restart the operating system on local and remote computers.
> Note: This command can only be used through PowerShell.
> See also: `shutdown`.
> More information: <https://learn.microsoft.com/powershell/module/microsoft.powershell.management/restart-computer>.

- Restart the local computer:

`Restart-Computer`

- Restart several computers:

`Restart-Computer -ComputerName {{Server01}}, {{Server02}}, localhost`

- Force an immediate restart of remote computers:

`Restart-Computer -ComputerName {{Server01}} -Credential {{Domain01\Admin01}} -Force`

- Restart a remote computer and wait until PowerShell is available on it again:

`Restart-Computer -ComputerName {{Server01}} -Wait -For PowerShell -Timeout {{300}} -Delay {{2}}`
