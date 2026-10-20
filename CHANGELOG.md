# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-20

### Added

- Initial release.
- Interactive ConPTY sessions for Windows PowerShell, PowerShell 7 and CMD.
- Tools: `terminal_start`, `terminal_send`, `terminal_read`, `terminal_wait`,
  `terminal_screen`, `terminal_interrupt`, `terminal_resize`, `terminal_list`,
  `terminal_stop`, `terminal_exec`.
- VT100 screen rendering, cursor-based incremental reads, blocking waits,
  named key sequences, multi-session support and UTF-8 output.
- Test suite (unit, integration against real shells, end-to-end MCP client).
