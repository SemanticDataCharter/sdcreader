# Security

Report a vulnerability privately to security@axius-sdc.com, or through GitHub's private vulnerability reporting
(Security tab, "Report a vulnerability"). Please do not open a public issue. The organization
policy is at https://github.com/SemanticDataCharter/.github/blob/main/SECURITY.md. Expect an acknowledgement within
three business days, and a fix released before anything is made public.

## Supported versions

| version | supported |
|---|---|
| 4.4.x | yes |
| earlier | no |

## The MCP server, as a threat model

`sdcreader-mcp` speaks JSON-RPC over stdio. There is no authentication and no network listener: whoever can write
to the process's stdin is the caller.

- **No tool takes a URL.** The catalog host is fixed when the server starts (`--host`, default SDCStudio's public
  catalog over https), so a caller cannot point the server at an arbitrary host. A tool takes either a model
  identifier, fetched from that host, or a package directory already on disk. When the catalog answers with a
  pointer to a stored artifact, the reader follows that pointer; the pointer comes from the host, not the caller.
- **File paths are the caller's.** A package directory is read, and a fetched package is saved only where the
  caller asks, as the process's user. Run it as an account that can read and write only what it should.
- **A package is checked before use.** A fetched or local package whose parts do not agree is refused.

Out of scope: the authenticity of a package the caller supplies from disk.
