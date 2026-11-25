# Clear-DnsClientCache

> Clear the contents of the DNS client cache. Equivalent to `ipconfig /flushdns`.
> Note: This command can only be used through PowerShell.
> See also: `ipconfig`.
> More information: <https://learn.microsoft.com/powershell/module/dnsclient/clear-dnsclientcache>.

- Clear the DNS client cache:

`Clear-DnsClientCache`

- Show what would happen without clearing the cache:

`Clear-DnsClientCache -WhatIf`

- Clear the DNS client cache on a remote computer:

`Clear-DnsClientCache -CimSession {{computer_name}}`
