# Resolve-DnsName

> Look up a DNS name. Similar to `nslookup`.
> Note: This command can only be used through PowerShell.
> More information: <https://learn.microsoft.com/powershell/module/dnsclient/resolve-dnsname>.

- Resolve a name:

`Resolve-DnsName -Name {{www.bing.com}}`

- Resolve a name using a specific DNS server:

`Resolve-DnsName -Name {{www.bing.com}} -Server {{10.0.0.1}}`

- Query a specific record type:

`Resolve-DnsName -Name {{www.bing.com}} -Type {{A}}`

- Resolve a name using DNS only, without LLMNR or NetBIOS:

`Resolve-DnsName -Name {{www.bing.com}} -DnsOnly`
