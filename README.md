# 🦜 polly-merge

Polls Bitbucket server open pull requests for a user and attempt to merge any
pull requests with a comment containing `@polly-merge merge`.

## Todo

Work in progress, remaining stuff:

- execute the merge attempt on matching pr's
- test with merge checks blocking the merge attempt
- actually output to the log file 😬
- maybe rework configuration to be a little less lame (list of params?)
- add some basic ci checks like black/pylint/sort imports at least

This should probably not be python but I'm reallllly lazy.

Keeping it dependency free at least so it has a chance of running on someone's
system.
