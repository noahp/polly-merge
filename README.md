# 🦜 polly-merge

Polls Bitbucket server open pull requests for a user and attempt to merge any
pull requests with a comment containing `@polly-merge merge`.

Get open pull requests:

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  "https://<BITBUCKET URL>/rest/api/1.0/dashboard/pull-requests?state=open&role=author"
```
