#!/usr/bin/env python3
"""
Polls open Bitbucket server pull requests for the user specified, and attempt to
merge any that have the "@polly-merge merge" string.

The following INPUTS are read from environment variables:

POLLY_MERGE_BITBUCKET_API_TOKEN - user's api token. needs write access to merge

POLLY_MERGE_BITBUCKET_URL - base url for the bitbucket server, eg https://foo.com

POLLY_MERGE_LOG_FILE - path to log file, defaults to ~/polly-merge.log .
polly-merge will write the following outputs into the file, if you want to hook
up fsnotify watchers or whatnot:
- successfuly merges
- failed merges

POLLY_MERGE_TRIGGER_COMMENT - modify the comment used to trigger merge,
  default is "@polly-merge merge"

polly-merge could be run via a cron job to have it operate asynchronously to
user action.

polly-merge is a broke person's bors-ng 😔
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


def http_operation(url, verb, headers={}, params={}):
    """
    execute the HTTP verb. return tuple of:
    ( <bool success?>, <response data>, <response headers> )
    """

    # encode the url-params
    if params:
        params = urllib.parse.urlencode(params)

    # always request JSON
    total_headers = {"Content-Type": "application/json"}
    total_headers.update(headers)

    # TODO we should be able to pass params as second field but doesn't work :(
    req = urllib.request.Request(url + "?" + params, None, total_headers, method=verb)

    try:
        with urllib.request.urlopen(req) as response:
            the_page = response.read()
    except urllib.error.HTTPError as e:
        print(e)
        return (False, None, None)

    # TODO pass response code? + headers
    return (True, the_page, None)


def post_url(url, headers={}, params={}):
    """Simple POST"""
    return http_operation(url, "POST", headers, params)


def get_url(url, headers={}, params={}):
    """Simple GET"""
    return http_operation(url, "GET", headers, params)


def main():
    """Program entrance point"""
    api_token = os.environ.get("POLLY_MERGE_BITBUCKET_API_TOKEN")
    assert api_token, "Please set POLLY_MERGE_BITBUCKET_API_TOKEN!"
    bitbucket_url = os.environ.get("POLLY_MERGE_BITBUCKET_URL")
    assert bitbucket_url, "Please set POLLY_MERGE_BITBUCKET_URL!"

    log_file = os.environ.get("POLLY_MERGE_LOG_FILE", "~/polly-merge.log")

    auth_header = {"Authorization": "Bearer " + api_token}

    # 1. get all open pull requests
    # this is a paginated api, so watch out:
    # https://docs.atlassian.com/bitbucket-server/rest/5.16.0/bitbucket-rest.html#paging-params
    pr_list = {"isLastPage": False}
    start = 0
    while not pr_list["isLastPage"]:
        pr_list_ok, pr_list_data, _ = get_url(
            bitbucket_url + "/rest/api/1.0/dashboard/pull-requests",
            headers=auth_header,
            params={"state": "open", "role": "author", "start": start},
        )
        assert pr_list_ok, "error fetching pr list"

        pr_list_data = json.loads(pr_list_data)

        # add this page of data
        pr_list.update(pr_list_data)

        # move to the next page
        if "nextPageStart" in pr_list_data:
            start = pr_list_data["nextPageStart"]
        else:
            break

    # TODO just print for now...
    print(json.dumps(pr_list["values"]))

    # 2. for each open pull request, look for the key comment

    # 3. attempt the merge; this can fail if the merge checks are not done (eg
    #    successful build, sufficient approvals, etc)


if __name__ == "__main__":
    main()
