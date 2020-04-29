# 🦜 polly-merge

[![License:
Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](http://unlicense.org/)

Polls your open pull requests on Bitbucket server, and attempts to merge any
pull requests that have a comment containing `@polly <COMMAND>` (configurable).

You might for example run it as a cron job, to background merge your pr's
instead of having to visit the bitbucket ui periodically.

It's kindof like a really bad version of one small piece of the
[bors-ng](https://github.com/bors-ng/bors-ng) idea, running on a local machine
and polling instead of a reasonable system design 😖 .

## Commands

### `merge`

Attempts to merge the PR, ex:

`@polly merge`

### `merge-after <pr url>`

Attempts to merge the PR only after the given PR has been merged, ex:

`@polly merge-after https://bitbucket-server.com/projects/PROJ/repos/some-repo/pull-requests/1234`

## Usage

**Requires** python3 to be installed.

You might set this up to be run with cron, eg:

```bash
# grab this repo
git clone https://github.com/noahp/polly-merge.git ~/polly-merge

# add the below entry to crontab
crontab -e
```

```crontab
# set your token + url into the environment vars
POLLY_MERGE_BITBUCKET_API_TOKEN=<your token>
POLLY_MERGE_BITBUCKET_URL=<your url>
# log to /tmp/polly-merge.log
*/5 * * * * ~/polly-merge/polly-merge.py >> /tmp/polly-merge.log
```

## Todo

Work in progress, remaining stuff:

- maybe rework configuration to be a little less lame (list of params?)
- add some basic ci checks like black/pylint/sort imports at least
- logging?

This should probably not be python but I'm reallllly lazy.

Keeping it dependency free at least so it has a chance of running on someone's
system.
