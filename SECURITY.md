# Security

Report a vulnerability privately through GitHub's private vulnerability reporting: open this repository's
Security tab and choose "Report a vulnerability" (https://github.com/SemanticDataCharter/sdcreader/security/advisories/new).
Please do not open a public issue, and do not send a report by email. The organization
policy is at https://github.com/SemanticDataCharter/.github/blob/main/SECURITY.md. Expect an acknowledgement within
three business days, and a fix released before anything is made public.

## Supported versions

| version | supported |
|---|---|
| 4.4.x | yes |
| earlier | upgrade |

## What counts as a vulnerability here

`sdcreader` reads a published Semantic Data Charter model's package and enumerates the values of a Governed Data
Record for projection into other standards, and ships an MCP server. A value present in a record that the reader
omits or misnumbers without saying so, or any way a malformed or hostile record or model package causes the reader
to read or write outside what the caller named, is in scope.

Out of scope: the authenticity of a model package or record the caller supplies.
