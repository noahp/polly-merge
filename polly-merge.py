#!/usr/bin/env python3
"""
Polls open Bitbucket server pull requests for the user specified, and attempt to
merge any that have the "@polly <COMMAND>" string in a comment.

The following INPUTS are read from environment variables:

POLLY_MERGE_BITBUCKET_API_TOKEN - user's api token. needs write access to merge

POLLY_MERGE_BITBUCKET_URL - base url for the bitbucket server, eg https://foo.com

POLLY_MERGE_TRIGGER_COMMENT - modify the comment used to trigger merge,
  default is "@polly"

POLLY_MERGE_LOG_FILE - file to output logs to, e.g. /tmp/polly-merge.log
  outputs to stdout if log file is not specified

polly-merge could be run via a cron job to have it operate asynchronously to
user action.

it outputs progress information to stderr, and the following information to
stdout:
- successful merges
- failed merges
eg for setting up fsnotify or something on the file where output is redirected.

polly-merge is a broke person's bors-ng 😔
"""

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from multiprocessing.dummy import Pool

try:
    from halo import Halo
except ImportError:

    class Halo(object):
        """Dummy class if the user doesn't have halo installed"""

        def __init__(self, text=None, stream=sys.stdout, *args, **kwargs):
            """Drop all args"""
            del args
            del kwargs
            if text:
                stream.write(text + "\n")

        def __enter__(self):
            """Just return the instance"""
            return self

        def succeed(self):
            """nothing"""
            pass

        def __exit__(self, type, value, traceback):
            """nothing"""
            pass


def http_operation(url, verb, headers=None, params=""):
    """
    execute the HTTP verb. return tuple of:
    ( <bool success?>, <response data>, <response headers> )
    """

    # encode the url-params
    if params:
        params = urllib.parse.urlencode(params)

    # always request JSON
    total_headers = {"Content-Type": "application/json"}
    if headers:
        total_headers.update(headers)

    # TODO we should be able to pass params as second field but doesn't work :(
    url = f"{url}?{params}"
    req = urllib.request.Request(url, None, total_headers, method=verb)

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            the_page = response.read()
    except urllib.error.HTTPError as exception:
        print(url)
        print(exception)
        return (False, None, None)

    # TODO pass response code? + headers
    return (True, the_page, None)


def post_url(url, headers=None, params=""):
    """Simple POST"""
    return http_operation(url, "POST", headers, params)


def get_url(url, headers=None, params=""):
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
            full_url, headers=headers, params=params
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


def recurse_comments(comments, comments_text):
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


def is_pr_merged(base_url, auth_header, pr_url_stem):
    """
    Check if a specific PR is merged
    Returns True if the specificed PR is merged False otherwise
    "pr_url_stem" should look like "/projects/<project name>/repos/<repo slug>/pull-requests/<pr id>"
    """
    result, response_json, _ = get_url(
        f"{base_url}/rest/api/1.0{pr_url_stem}", headers=auth_header
    )

    if not result:
        return False

    response = json.loads(response_json)
    pr_state = response.get("state", "")
    return pr_state == "MERGED"


def merge_pr(base_url, auth_header, projectkey, repositoryslug, pullrequestid, version):
    """
    Merge the specified pr.

    Api is
    projects/{projectkey}/repos/{repositoryslug}/pull-requests/{pullrequestid}/merge?version

    Returns True if sucessful False otherwise
    """

    # check if the PR is ready to merge
    pr_merge_url = f"{base_url}/rest/api/1.0/projects/{projectkey}/repos/{repositoryslug}/pull-requests/{pullrequestid}/merge"
    result, response_json, _ = get_url(pr_merge_url, headers=auth_header)

    if not result:
        return (False, f"error fetching {pr_merge_url}")

    response = json.loads(response_json)
    canMerge = response.get("canMerge")
    if not canMerge:
        return (False, str(response_json))

    # now try to merge
    result, _, _ = post_url(
        pr_merge_url, headers=auth_header, params={"version": version}
    )

    return (result, "")


def process_pr(pr_data, bitbucket_url, auth_header, merge_trigger):
    """
    Process a single pr from the pr json data returned from the dashboard api
    Returns:
    - None if merge_trigger wasn't detected
    - tuple(
        <pr url string>,
        tuple(
            <bool success or failure>, <string of failure reason>
        ),
      )
    """
    pr_url = pr_data["links"]["self"][0]["href"]
    # print(json.dumps(pr_data))
    repositoryslug = pr_data["toRef"]["repository"]["slug"]
    projectkey = pr_data["toRef"]["repository"]["project"]["key"]
    pullrequestid = pr_data["id"]

    def get_comments():
        return get_all_comments(
            bitbucket_url, auth_header, projectkey, repositoryslug, pullrequestid
        )

    def just_merge(match):
        """Issue a non conditional merge"""
        del match
        merge_ok = merge_pr(
            bitbucket_url,
            auth_header,
            projectkey,
            repositoryslug,
            pullrequestid,
            pr_data["version"],
        )
        return (pr_url, merge_ok)

    def merge_after(match):
        """Issue a merge if the matched url is merged"""
        other_pr_url = match[1]
        other_pr_url_stem = urllib.parse.urlsplit(other_pr_url)[2]

        # basic sanity check URL is valid
        # strip off anything post PR-ID (such as /overview /diff)
        match = re.match(
            "(/projects/.*/repos/.*/pull-requests/[0-9]*)[/.*]?", other_pr_url_stem
        )
        if not match:
            return (pr_url, (False, f"invalid pr_url {other_pr_url}"))

        if is_pr_merged(bitbucket_url, auth_header, match[1]):
            return just_merge(match)
        else:
            return (pr_url, (False, f"{other_pr_url} not merged yet!"))

    # dictionary of regex-pattern: command to run on match
    commands = {
        # command: merge
        re.compile(f"{merge_trigger} merge$"): just_merge,
        # command: merge-after <url>
        re.compile(f"{merge_trigger} merge-after (.*)$"): merge_after,
    }

    def process_commands(list_to_check):
        """Check for match and run command on list_to_check"""
        for pattern, command in commands.items():
            if match := list(filter(None, map(pattern.match, list_to_check))):
                return command(match[0])
        return None

    # check PR description then comments. order is important; we don't want to
    # do the relatively expensive fetch of comments for a PR if the description
    # has a match
    return process_commands([pr_data.get("description", "")]) or process_commands(
        get_comments()
    )



def main():
    """Program entrance point"""
    api_token = os.environ.get("POLLY_MERGE_BITBUCKET_API_TOKEN")
    assert api_token, "Please set POLLY_MERGE_BITBUCKET_API_TOKEN!"
    bitbucket_url = os.environ.get("POLLY_MERGE_BITBUCKET_URL")
    assert bitbucket_url, "Please set POLLY_MERGE_BITBUCKET_URL!"

    log_file = os.environ.get("POLLY_MERGE_LOG_FILE")

    merge_trigger = os.environ.get("POLLY_MERGE_TRIGGER_COMMENT", "@polly")

    auth_header = {"Authorization": "Bearer " + api_token}

    if log_file:
        # output to specified log file if variable is set
        logging.basicConfig(
            format="%(asctime)s $(message)s",
            level=logging.INFO,
            filename=log_file,
            filemode="w",
        )
    else:
        # default logging to stdout if no log file is specified
        logging.basicConfig(
            format="%(asctime)s %(message)s", level=logging.INFO, stream=sys.stdout
        )

    # 1. get all open pull requests
    with Halo(text="Loading open PRs", spinner="dots", stream=sys.stderr) as spinner:
        pr_list = get_open_prs(bitbucket_url, auth_header)
        spinner.succeed()

    # # DEBUG use when debugging json to dump to file and load
    # print(json.dumps(pr_list))
    # with open("prs2.json", "r") as pr_json:
    #     pr_list = json.load(pr_json)

    # 2. for each open pull request, look for the key comment and attempt merge

    # use multiprocessing.dummy.Pool to use threads instead of multiple
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

    # issue all the pr data requests simultaneously (up to 50). most won't
    # require paging (>25 "activities") so this should be pretty good
    with Halo(
        text="Checking PRs for merge comment", spinner="dots", stream=sys.stderr
    ) as spinner:
        with Pool(min(50, len(pr_list))) as pool:
            results = pool.map(process_pr_wrapper, pr_list)
        spinner.succeed()

    # output results from process_pr_wrapper.
    # the return value is a tuple:
    # ('PR URL', (True/False <success code>, string <extra info>))
    for merged in filter(None, results):
        if merged[1][0]:
            logging.info(f"Merged {merged[0]}")
        else:
            logging.info(f"Failed to merge {merged[0]} : {merged[1][1]}")


if __name__ == "__main__":
    main()
