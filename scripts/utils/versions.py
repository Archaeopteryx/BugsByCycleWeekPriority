# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import datetime
import json

import urllib.request

VERSION_INFO_URL = "https://product-details.mozilla.org/1.0/firefox.json"

def get_release_versions_for_weeks(time_intervals):
    with urllib.request.urlopen(VERSION_INFO_URL) as request_handle:
        data = json.loads(request_handle.read())
    major_releases_data = [release_data for release_data in data["releases"].values() if release_data["category"] == "major"]
    major_releases_data = sorted(major_releases_data, key=lambda data: data["date"])
    release_version_by_week = {}
    for time_interval in time_intervals:
        # day is defined as start of day
        end_day_str = (time_interval["to"] - datetime.timedelta(1)).isoformat()
        release_version_by_week[end_day_str] = [release_data for release_data in major_releases_data if release_data["date"] <= end_day_str][-1]["version"].split(".")[0]
    return release_version_by_week

