# MacBook Actions runner

Trusted Linux jobs use `[self-hosted, Linux, X64, macbook-linux]`. A host service polls GitHub and starts one ephemeral repository runner at a time in an isolated Ubuntu 24.04 VM. The x64 userspace runs through Rosetta on the Apple Silicon Mac. No personal directories or SSH agent are mounted. The VM disk is restored from its clean baseline before each job.

The service starts at login, restarts after failure, and keeps the Mac awake on mains power. Network access and an unlocked login after reboot are required. When the laptop is unavailable, jobs wait in GitHub's queue; they do not automatically become paid hosted jobs. Fork pull requests and actors outside the configured trusted list retain GitHub-hosted runners. Disabled workflows and dormant forks are not enabled by this migration.

Service: `com.sgill.github-actions-mac`. Configuration, status, rotating logs, and receipts live in `~/.local/share/github-actions-mac/`. The controller uses the host's existing GitHub CLI authentication; only a single-use repository runner credential enters the VM. A single-job limit and free-disk checks bound resource usage. Automatic cleanup deletes runner logs after 7 days and completed job evidence after 14 days, preserving active jobs and unrecognised files. VM workspaces and dependencies are discarded between jobs.

GitHub artifact storage is a separate quota. Workflows using `retain-evidence` retain selected files and SHA-256 manifests on the MacBook, collected after the job under `evidence/<repository>/<run>-<attempt>-<job>/`. These files are local evidence, not GitHub artifacts or hosted attestations. Other workflows retain their existing artifact and release-provenance contracts.

The macOS application matrix and signed release retain the Apple Silicon and Intel GitHub-hosted machines. A single Apple Silicon laptop does not reproduce that OS/hardware test matrix.
