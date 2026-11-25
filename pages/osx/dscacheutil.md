# dscacheutil

> Query and flush the Directory Service cache, which also caches host (DNS) lookups.
> More information: <https://keith.github.io/xcode-man-pages/dscacheutil.1.html>.

- Flush the entire Directory Service cache:

`sudo dscacheutil -flushcache`

- Look up a host by name:

`dscacheutil -q host -a name {{example.com}}`

- Look up a host by IP address:

`dscacheutil -q host -a ip_address {{192.168.0.1}}`

- Look up a user by name:

`dscacheutil -q user -a name {{username}}`

- List all entries in a category:

`dscacheutil -q {{user|group|host|mount|protocol|rpc|service}}`
