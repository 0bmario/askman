# dscl

> Read and manage Directory Service data, such as local user and group records.
> More information: <https://keith.github.io/xcode-man-pages/dscl.1.html>.

- Read a user record in the local directory node:

`dscl . -read /Users/{{username}}`

- List all local users with their user ID:

`dscl . -list /Users UniqueID`

- List all local groups:

`dscl . -list /Groups`

- Read a group record in the local directory node:

`dscl . -read /Groups/{{group_name}}`

- Search local users for records whose attribute has a given value:

`dscl . -search /Users {{UserShell}} {{/bin/zsh}}`
