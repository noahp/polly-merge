# 🦜 polly-merge

[![License:
Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg?style=for-the-badge)](http://unlicense.org/)
[![Code style:
black](https://img.shields.io/badge/code%20style-black-000000.svg?style=for-the-badge)](https://github.com/ambv/black)
[![GitHub Workflow
Status](https://img.shields.io/github/workflow/status/noahp/polly-merge/main-ci?style=for-the-badge)](https://github.com/noahp/polly-merge/actions)
[![LGTM](https://img.shields.io/lgtm/alerts/github/noahp/polly-merge?style=for-the-badge)](https://lgtm.com/projects/g/noahp/polly-merge/)

Polls your open pull requests on Bitbucket server, and attempts to merge any
pull requests that have a comment/description containing `@polly <COMMAND>`
(configurable).

_NOTE: this is for use with the Bitbucket Server 1.0 REST API, it won't work
  with Bitbucket Cloud (which disabled the 1.0 API a while back)._

You might for example run it as a cron job, to background merge your pr's
instead of having to visit the bitbucket ui periodically.

It's kindof like a really bad version of one small piece of the
[bors-ng](https://github.com/bors-ng/bors-ng) idea, running on a local machine
and polling instead of a reasonable system design 😖 .

## Commands

### `@polly merge`

Attempts to merge the PR.

### `@polly merge-after <pr url>`

Attempts to merge the PR only after the given PR has been merged, ex:

`@polly merge-after https://bitbucket-server.com/projects/PROJ/repos/some-repo/pull-requests/1234`

## Usage

**Requires** python3 to be installed.

You might set this up to be run with cron, eg:

```bash
# grab this repo
git clone https://github.com/noahp/polly-merge.git ~/polly-merge
```

Then add the below entry to crontab, eg run `crontab -e`:

```crontab
# set your token + url into the environment vars
POLLY_MERGE_BITBUCKET_API_TOKEN=<your token>
POLLY_MERGE_BITBUCKET_URL=<your url>
*/5 * * * * ~/polly-merge/polly-merge.py
```

See [`polly-merge.py`](polly-merge.py) for additional options.

## Todo

Work in progress, remaining stuff:

- maybe rework configuration to be a little less lame (list of params?)
- add fake bitbucket server api 1.0

This should probably not be python but I'm reallllly lazy.

Keeping it dependency free at least so it has a chance of running on someone's
system.

## Developing

You can run whatever tests CI runs by executing the [./test.sh](test.sh) script
(requires Docker; everything runs in a container).
