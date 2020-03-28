#!/usr/bin/env python3
"""
Polls open Bitbucket server pull requests for the user specified, and attempt to
merge any that have the "@polly-merge merge" string in a comment.

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


def http_operation(url, verb, headers=None, params=None):
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
    req = urllib.request.Request(f"{url}?{params}", None, total_headers, method=verb)

    try:
        with urllib.request.urlopen(req) as response:
            the_page = response.read()
    except urllib.error.HTTPError as exception:
        print(exception)
        return (False, None, None)

    # TODO pass response code? + headers
    return (True, the_page, None)


def post_url(url, headers=None, params=None):
    """Simple POST"""
    return http_operation(url, "POST", headers, params)


def get_url(url, headers=None, params=None):
    """Simple GET"""
    return http_operation(url, "GET", headers, params)


def get_paged_api(full_url, headers, params=None):
    """
    read a "paged api", return the values field
    https://docs.atlassian.com/bitbucket-server/rest/5.16.0/bitbucket-rest.html#paging-params
    """
    if not params:
        params = {}
    page_data = {"isLastPage": False, "values": []}
    start = 0
    while not page_data["isLastPage"]:
        params.update({"start": start})

        print(full_url)
        single_page_ok, single_page_data, _ = get_url(
            full_url,
            headers=headers,
            params=params,
        )
        assert single_page_ok, "error fetching list"

        single_page_data = json.loads(single_page_data)

        # add this page of data
        page_data["values"].extend(single_page_data["values"])
        page_data["isLastPage"] = single_page_data.get(
            "isLastPage", page_data["isLastPage"]
        )

        # move to the next page
        if "nextPageStart" in single_page_data:
            start = single_page_data["nextPageStart"]
        else:
            break

    return page_data["values"]


def get_open_prs(base_url, auth_header):
    """Return list of open prs"""
    return get_paged_api(
        f"{base_url}/rest/api/1.0/dashboard/pull-requests",
        headers=auth_header,
        params={"state": "open", "role": "author"},
    )

def recurse_comments(comment, comment_texts=[]):
    """
    recurse nested comments. the activities api returns stuff like:

    "comment": {
        "id": 1158611,
        "text": "some text",
        ...
        "comments": [
          {
            ...
            "id": 1158922,
            "text": "some text"

    etc. so recurse through it
    """

    return comment_texts

def get_all_comments(base_url, auth_header, projectkey, repositoryslug, pullrequestid):
    """get comments for a pr"""

    # The "comments" rest api sucks. You have to specify a path (to a file in
    # the diff) for comments, so you can't see general comments. Use the
    # activities api instead, and parse it for comments
    # /REST/API/1.0/projects/{projectkey}/repos/{repositoryslug}/pull-requests/{pullrequestid}/activities
    activities = get_paged_api(
        f"{base_url}/rest/api/1.0/projects/{projectkey}/repos/{repositoryslug}/pull-requests/{pullrequestid}/activities",
        headers=auth_header,
    )

    comments = []



def main():
    """Program entrance point"""
    api_token = os.environ.get("POLLY_MERGE_BITBUCKET_API_TOKEN")
    assert api_token, "Please set POLLY_MERGE_BITBUCKET_API_TOKEN!"
    bitbucket_url = os.environ.get("POLLY_MERGE_BITBUCKET_URL")
    assert bitbucket_url, "Please set POLLY_MERGE_BITBUCKET_URL!"

    log_file = os.environ.get("POLLY_MERGE_LOG_FILE", "~/polly-merge.log")

    auth_header = {"Authorization": "Bearer " + api_token}

    # 1. get all open pull requests
    # pr_list = get_open_prs(bitbucket_url, auth_header)

    # DEBUG
    with open("prs.json", "r") as pr_json:
        pr_list = json.load(pr_json)

    # 2. for each open pull request, look for the key comment
    for pr in pr_list:
        repo_slug = pr["toRef"]["repository"]["slug"]
        project_id = pr["toRef"]["repository"]["project"]["key"]
        # print(pr["links"]["self"][0]["href"])
        print(json.dumps(pr))

        # print(
        #     get_all_comments(
        #         bitbucket_url,
        #         auth_header,
        #         pr["toRef"]["repository"]["project"]["key"],
        #         pr["toRef"]["repository"]["slug"],
        #         pr["id"],
        #     )
        # )
        break

    # 3. attempt the merge; this can fail if the merge checks are not done (eg
    #    successful build, sufficient approvals, etc)


if __name__ == "__main__":
    main()
