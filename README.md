# Creative Destruction 2.0 — update downloads

Official public transport mirror for [cd2game.com](https://cd2game.com/).

The launcher checks the official API for the current signed BT release. This repository only distributes the exact files named by SHA-256. GitHub does not select the game version, sign updates, authenticate accounts, or host the game servers.

## Publishing a new mirror

1. Publish the signed BT update through the existing official deployment process.
2. Open **Actions → Mirror signed CD2 update artifacts → Run workflow**, using `main`. Alternatively commit a new `publish-request.json` containing the release name to trigger the same workflow.
3. The job downloads the public artifacts directly from cd2game.com, verifies their size and SHA-256, and uploads only missing files to a draft Release.
4. After every artifact is verified, it publishes the Release and updates `channels/blobs-v1.json` atomically. Existing hash-addressed files are reused.

No personal access token or additional repository secret is required: the job uses GitHub's temporary workflow token. Never upload signing keys, server configuration, account data, database files, or private launcher configuration.

## Downloads and safety

- A compatible launcher uses public Releases with HTTPS and range requests, without a GitHub account.
- Signed manifests and exact file hashes still authorize every installed byte.
- If the mirror is missing or unavailable, the launcher uses the original official server.
- Each GitHub asset must be smaller than 2 GiB. Larger artifacts are refused by the publisher rather than silently truncated.
- This mirror does not install a new game version by itself, and does not change the game's renderer or settings.

Launcher support for this transport starts with version **0.4.7**. Earlier launchers continue using the original download endpoint until upgraded.
