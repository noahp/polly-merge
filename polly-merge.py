#!/usr/bin/env python3
"""
Polls open Bitbucket server pull requests for the user specified, and attempt to
merge any that have the "@polly <COMMAND>" string in a comment.

The following INPUTS are read from environment variables:

POLLY_MERGE_BITBUCKET_API_TOKEN - user's api token. needs write access to merge

POLLY_MERGE_BITBUCKET_URL - base url for the bitbucket server, eg https://foo.com

POLLY_MERGE_ANY_USER_COMMENT - if falsy ("false", "0", etc) or unset, only
comments supplied by the authenticating user will trigger action. if truthy, any
user's comment will trigger the action

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

import configparser
import dataclasses
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from distutils import util as distutils_util
from multiprocessing.dummy import Pool

try:
    import coloredlogs

    coloredlogs.install(level=logging.INFO, milliseconds=True)
except ImportError:
    pass

try:
    from halo import Halo
except ImportError:

    class Halo:
        """Dummy class if the user doesn't have halo installed"""

        def __init__(self, *args, text=None, stream=sys.stdout, **kwargs):
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

        def __exit__(self, exc_type, exc_value, exc_traceback):
            """nothing"""


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


class BitbucketApi:
    """Used to interact with the bitbucket api"""

    def __init__(self, base_url, auth_header):
        self.base_url = base_url
        self.auth_header = auth_header

    def get_open_prs(self):
        """Return list of open prs"""
        return get_paged_api(
            f"{self.base_url}/rest/api/1.0/dashboard/pull-requests",
            headers=self.auth_header,
            params={"state": "open", "role": "author"},
        )

    @staticmethod
    def recurse_comments(comments, comments_text, username_filter):
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

        If username_filter is not None, only comments written by that user will
        be returned.
        """
        for comment in comments:
            if username_filter is None or comment["author"]["name"] == username_filter:
                comments_text.append(comment["text"])
            BitbucketApi.recurse_comments(
                comment["comments"], comments_text, username_filter
            )

    def get_all_comments(
        self, projectkey, repositoryslug, pullrequestid, username_filter
    ):
        """
        get comments for a pr
        If username_filter is not None, only comments written by that user will
        be returned.
        """

        # The "comments" rest api sucks. You have to specify a path (to a file in
        # the diff) for comments, so you can't see general comments. Use the
        # activities api instead, and parse it for comments
        # /REST/API/1.0/projects/{projectkey}/repos/{repositoryslug}/pull-requests/{pullrequestid}/activities
        activities = get_paged_api(
            f"{self.base_url}/rest/api/1.0/projects/{projectkey}/repos/{repositoryslug}/pull-requests/{pullrequestid}/activities",
            headers=self.auth_header,
        )

        comments_text = []
        for activity in activities:
            if activity["action"] == "COMMENTED":
                comment = activity["comment"]

                # for now, just add the raw text from each comment
                if (
                    username_filter is None
                    or comment["author"]["name"] == username_filter
                ):
                    comments_text.append(comment["text"])

                # recurse through nested comments
                self.recurse_comments(
                    comment["comments"], comments_text, username_filter
                )

        return comments_text

    def is_pr_merged(self, pr_url_stem):
        """
        Check if a specific PR is merged
        Returns True if the specified PR is merged False otherwise
        "pr_url_stem" should look like "/projects/<project name>/repos/<repo slug>/pull-requests/<pr id>"
        """
        result, response_json, _ = get_url(
            f"{self.base_url}/rest/api/1.0{pr_url_stem}", headers=self.auth_header
        )

        if not result:
            return False

        response = json.loads(response_json)
        pr_state = response.get("state", "")
        return pr_state == "MERGED"

    def merge_pr(self, projectkey, repositoryslug, pullrequestid, version):
        """
        Merge the specified pr.

        Api is
        projects/{projectkey}/repos/{repositoryslug}/pull-requests/{pullrequestid}/merge?version

        Returns True if sucessful False otherwise
        """

        # check if the PR is ready to merge
        pr_merge_url = f"{self.base_url}/rest/api/1.0/projects/{projectkey}/repos/{repositoryslug}/pull-requests/{pullrequestid}/merge"
        result, response_json, _ = get_url(pr_merge_url, headers=self.auth_header)

        if not result:
            return (False, f"error fetching {pr_merge_url}")

        response = json.loads(response_json)
        canmerge = response.get("canMerge")
        if not canmerge:
            return (False, str(response_json))

        # now try to merge
        result, _, _ = post_url(
            pr_merge_url, headers=self.auth_header, params={"version": version}
        )

        return (result, "")

    def process_pr(self, pr_data, merge_trigger, current_user_only_comments):
        """
        Process a single pr from the pr json data returned from the dashboard api

        Set current_user_only_comments to only trigger on comments by the
        current user (eg same as pr author).

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

        if current_user_only_comments:
            username = pr_data["author"]["user"]["name"]
        else:
            username = None

        def get_comments():
            return self.get_all_comments(
                projectkey, repositoryslug, pullrequestid, username
            )

        def just_merge(match):
            """Issue a non conditional merge"""
            del match
            merge_ok = self.merge_pr(
                projectkey, repositoryslug, pullrequestid, pr_data["version"],
            )
            return (pr_url, merge_ok)

        def merge_after(match):
            """Issue a merge if the matched url is merged"""
            other_pr_url = match[1]
            other_pr_url_stem = urllib.parse.urlsplit(other_pr_url)[2]

            # basic sanity check URL is valid
            # strip off anything post PR-ID (such as /overview /diff)
            match = re.match(
                "(/(?:projects|users)/.*/repos/.*/pull-requests/[0-9]*)[/.*]?",
                other_pr_url_stem,
            )
            if not match:
                return (pr_url, (False, f"invalid pr_url {other_pr_url}"))

            if self.is_pr_merged(match[1]):
                return just_merge(match)

            return (pr_url, (False, f"{other_pr_url} not merged yet!"))

        # dictionary of regex-pattern: command to run on match
        commands = {
            # command: merge
            f"^{merge_trigger} merge$": just_merge,
            # command: merge-after <url>
            f"^{merge_trigger} merge-after (.*)$": merge_after,
        }

        def process_commands(list_to_check):
            """Check for match and run command on list_to_check"""
            for pattern, command in commands.items():
                regex = re.compile(pattern, re.MULTILINE)
                match = list(filter(None, map(regex.search, list_to_check)))
                if match:
                    return command(match[0])
            return None

        # check PR description then comments. order is important; we don't want to
        # do the relatively expensive fetch of comments for a PR if the description
        # has a match
        return process_commands([pr_data.get("description", "")]) or process_commands(
            get_comments()
        )


@dataclasses.dataclass
class PollyConfig:
    """
    Configuration settings
    """

    bitbucket_api_token: str = ""
    bitbucket_url: str = ""
    any_user_comment: bool = False
    log_file: str = ""
    merge_trigger: str = "@polly"

    def __setattr__(self, name, value):
        """Parse from str for typed values"""
        if name == "any_user_comment":
            if isinstance(value, str):
                self.any_user_comment = distutils_util.strtobool(value)
            elif isinstance(value, bool):
                super(PollyConfig, self).__setattr__(name, value)
            else:
                raise ValueError(f"whoops, {value} is unsupported type {type(value)}")
        else:
            super(PollyConfig, self).__setattr__(name, value)

    def mandatory_field_check(self):
        """Assert on any mandatory fields that aren't set"""
        for field in ("bitbucket_api_token", "bitbucket_url"):
            assert self.__getattribute__(field), f"Error! must set {field}"


def find_ini_file():
    """Locate polly-merge.ini"""

    # sources, in order of highest precedence to lowest
    inifile_sources = (
        # env car
        os.environ.get("POLLY_MERGE_CONFIG_FILE"),
        # cwd
        "./polly-merge.ini" if os.path.isfile("./polly-merge.ini") else None,
        # next to this script
        os.path.join(os.path.dirname(__file__))
        if os.path.isfile(os.path.join(os.path.dirname(__file__)))
        else None,
    )
    return next(filter(None, inifile_sources), None)


def load_configuration():
    """
    Load configuration settings. Hierarchy is:

    - polly-merge.ini (POLLY_MERGE_CONFIG_FILE env var, or cwd, or this file
      adjacent)
    - env vars will override settings in that file
    """
    config = PollyConfig()
    inifile = find_ini_file()

    if inifile:
        # load settings from inifile
        cfg = configparser.ConfigParser()
        cfg.read(inifile)
        if "DEFAULT" in cfg:
            for key, value in cfg["DEFAULT"].items():
                config.__setattr__(key.lower(), value)

    # load env variables
    for field in dataclasses.fields(config):
        val = os.environ.get(f"POLLY_MERGE_{field.name.upper()}")
        if val:
            config.__setattr__(field.name, val)

    # check mandatory fields
    config.mandatory_field_check()

    return config


def main():
    """Program entrance point"""
    config = load_configuration()

    auth_header = {"Authorization": "Bearer " + config.bitbucket_api_token}

    # shared logging setup
    logging_setup = {
        "format": "%(asctime)s %(message)s",
        "level": logging.INFO,
    }

    if config.log_file:
        # output to specified log file if variable is set
        logging_setup.update({"filename": config.log_file, "filemode": "a"})
    else:
        # default logging to stdout if no log file is specified
        logging_setup.update({"stream": sys.stdout})

    logging.basicConfig(**logging_setup)

    bitbucket = BitbucketApi(base_url=config.bitbucket_url, auth_header=auth_header)

    # 1. get all open pull requests
    with Halo(text="Loading open PRs", spinner="dots", stream=sys.stderr) as spinner:
        pr_list = bitbucket.get_open_prs()
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
        return bitbucket.process_pr(
            pr_data, config.merge_trigger, not config.any_user_comment
        )

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
