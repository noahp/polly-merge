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
from multiprocessing.dummy import Pool

try:
    from halo import Halo
except ImportError:

    class Halo(object):
        """Dummy class if the user doesn't have halo installed"""

        def __init__(self, text=None, *args, **kwargs):
            """Drop all args"""
            del args
            del kwargs
            print(text)

        def __enter__(self):
            """Just return the instance"""
            return self

        def succeed(self):
            """nothing"""
            pass

        def __exit__(self, type, value, traceback):
            """nothing"""
            pass


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
        with urllib.request.urlopen(req, timeout=5) as response:
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

        single_page_ok, single_page_data, _ = get_url(
            full_url, headers=headers, params=params,
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


def recurse_comments(comments, comments_text=[]):
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
    for comment in comments:
        comments_text.append(comment["text"])
        recurse_comments(comment["comments"], comments_text)


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

    comments_text = []
    for activity in activities:
        if activity["action"] == "COMMENTED":
            comment = activity["comment"]

            # for now, just add the raw text from each comment
            comments_text.append(comment["text"])

            # recurse through nested comments
            recurse_comments(comment["comments"], comments_text)

    return comments_text


def process_pr(pr_data, bitbucket_url, auth_header, merge_trigger):
    """Process a single pr from the pr json data returned from the dashboard api"""
    repo_slug = pr_data["toRef"]["repository"]["slug"]
    project_id = pr_data["toRef"]["repository"]["project"]["key"]
    pr_url = pr_data["links"]["self"][0]["href"]
    # print(json.dumps(pr_data))

    all_comments = get_all_comments(
        bitbucket_url,
        auth_header,
        pr_data["toRef"]["repository"]["project"]["key"],
        pr_data["toRef"]["repository"]["slug"],
        pr_data["id"],
    )

    # look for exact match in any comment
    if merge_trigger in all_comments:
        # TODO actually merge ...
        return f"Merged {pr_url} !"


def main():
    """Program entrance point"""
    api_token = os.environ.get("POLLY_MERGE_BITBUCKET_API_TOKEN")
    assert api_token, "Please set POLLY_MERGE_BITBUCKET_API_TOKEN!"
    bitbucket_url = os.environ.get("POLLY_MERGE_BITBUCKET_URL")
    assert bitbucket_url, "Please set POLLY_MERGE_BITBUCKET_URL!"

    log_file = os.environ.get("POLLY_MERGE_LOG_FILE", "~/polly-merge.log")

    merge_trigger = os.environ.get("POLLY_MERGE_TRIGGER_COMMENT", "@polly-merge merge")

    auth_header = {"Authorization": "Bearer " + api_token}

    # 1. get all open pull requests
    with Halo(text="Loading open PRs", spinner="dots") as spinner:
        pr_list = get_open_prs(bitbucket_url, auth_header)
        spinner.succeed()

    # # DEBUG use when debugging json to dump to file and load
    # print(json.dumps(pr_list))
    # with open("prs2.json", "r") as pr_json:
    #     pr_list = json.load(pr_json)

    # 2. for each open pull request, look for the key comment

    # user multiprocessing.dummy.Pool to use threads instead of multiple
    # processes; this is simpler than using normal multiprocessing, because we
    # want to pass through the config options (from env variables), and
    # multiprocessing needs a hashable callable to run Pool.map.
    #
    # using python threads is suitable here because the http calls are the
    # blocking ones, so they do a decent job yielding. using a pool speeds this
    # up dramatically if there's lots of open pr's, because we spend most of the
    # time waiting on the server
    def process_pr_wrapper(pr_data):
        return process_pr(pr_data, bitbucket_url, auth_header, merge_trigger)

    # issue all the pr data requests simultaneously. most won't require paging
    # (>25 "activities") so this should be pretty good
    with Halo(text="Checking PRs for merge comment", spinner="dots") as spinner:
        with Pool(len(pr_list)) as pool:
            results = pool.map(process_pr_wrapper, pr_list)
        spinner.succeed()

    print("\n".join(filter(None, results)))

    # 3. attempt the merge; this can fail if the merge checks are not done (eg
    #    successful build, sufficient approvals, etc)


if __name__ == "__main__":
    main()
