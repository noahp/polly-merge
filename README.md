# 🦜 polly-merge

Polls Bitbucket server open pull requests for a user and attempt to merge any
pull requests with a comment containing `@polly-merge merge`.

You might for example run it as a cron job to background merge your pr's instead
of having to visit the bitbucket ui periodically.

It's kindof like a really bad version of one small piece of the
[bors-ng](https://github.com/bors-ng/bors-ng) idea, running on a local machine
and polling instead of a reasonable system design 😖 .

## Todo

Work in progress, remaining stuff:

- actually output to the log file 😬
- maybe rework configuration to be a little less lame (list of params?)
- add some basic ci checks like black/pylint/sort imports at least

This should probably not be python but I'm reallllly lazy.

Keeping it dependency free at least so it has a chance of running on someone's
system.
