# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import csv
import datetime
import json
from libmozdata.bugzilla import Bugzilla
from logger import logger
import productdates
import pytz
import urllib.request
import sys

from utils.bugzilla import BUG_LIST_WEB_URL, get_relevant_bug_changes

import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

from config.firefox_team import PRODUCTS_TO_CHECK, PRODUCTS_COMPONENTS_TO_CHECK

RESOLUTIONS_IGNORED = ['INVALID']
STATUS_OPEN_CONFIRMED = ['NEW', 'ASSIGNED', 'REOPENED']


def get_regressions_added(label, start_date, end_date):

    def bug_handler(bug_data):
        if bug_data['id'] in [data['id'] for data in bugs_data]:
            return
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "severity", "status", "resolution", "keywords"], start_date, end_date)
        if [bug_states["product"]["new"], bug_states["component"]["new"]] not in PRODUCTS_COMPONENTS_TO_CHECK:
            return
        if bug_states["status"]["new"] == "UNCONFIRMED":
            return
        if bug_states["resolution"]["new"] in RESOLUTIONS_IGNORED:
            return
        if "regression" not in bug_states["keywords"]["new"]:
            return
        if "perf-alert" in bug_data["keywords"]:
            # Exclude bugs which have been filed with the keyword 'perf-alert'.
            # Include bugs which got 'perf-alert' keyword later. In this case the
            # bug wasn't created for a performance regression and the alert
            # should be an performance improvement which got posted as a comment.
            perfAlertAdded = False
            for historyItem in bug_data["history"]:
                for change in historyItem["changes"]:
                    if change["field_name"] == "keywords" and "perf-alert" in change["added"].split(", "):
                        perfAlertAdded = True
                if not perfAlertAdded:
                    return
        if datetime.datetime.strptime(bug_data["creation_time"], '%Y-%m-%dT%H:%M:%SZ').date() < start_date:
            if [bug_states["product"]["old"], bug_states["component"]["old"]] in PRODUCTS_COMPONENTS_TO_CHECK and \
              bug_states["status"]["old"] != "UNCONFIRMED" and \
              "regression" in bug_states["keywords"]["old"]:
                return
            if [bug_states["product"]["old"], bug_states["component"]["old"]] not in PRODUCTS_COMPONENTS_TO_CHECK or \
              bug_states["status"]["old"] == "UNCONFIRMED" or \
              "regression" not in bug_states["keywords"]["old"]:
                bugs_data.append({
                  'id': bug_data['id'],
                  'severity': bug_states["severity"]["new"],
                })
        else:
            bugs_data.append({
              'id': bug_data['id'],
              'severity': bug_states["severity"]["new"],
            })

    showDebug = False

    bugs_data = []

    fields = [
              'id',
              'product',
              'component',
              'severity',
              'status',
              'resolution',
              'keywords',
              'creation_time',
              'history',
             ]

    params = {
        'include_fields': fields,
        'f1': 'OP',
        'j1': 'AND_G',
        'f2': 'keywords',
        'o2': 'changedafter',
        'v2': start_date,
        'f3': 'keywords',
        'o3': 'changedbefore',
        'v3': end_date,
        'f4': 'CP',
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'f1': 'keywords',
        'o1': 'allwords',
        'v1': 'regression',
        'f2': 'OP',
        'j2': 'AND',
        'f3': 'creation_ts',
        'o3': 'greaterthan',
        'v3': start_date,
        'f4': 'creation_ts',
        'o4': 'lessthan',
        'v4': end_date,
        'f5': 'CP',
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'f1': 'OP',
        'j1': 'AND_G',
        'f2': 'bug_status',
        'o2': 'changedfrom',
        'v2': 'UNCONFIRMED',
        'f3': 'bug_status',
        'o3': 'changedafter',
        'v3': start_date,
        'f4': 'bug_status',
        'o4': 'changedbefore',
        'v4': end_date,
        'f5': 'CP',
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    return bugs_data


def get_bugs(time_interval):
    start_date = time_interval['from']
    end_date = time_interval['to']
    label = time_interval['label']
    data = {}
    data['regressions_added'] = get_regressions_added(label, start_date, end_date)

    return data


def measure_data(time_intervals):
    data_by_time_intervals = []
    for time_interval in time_intervals:
        data_by_time_intervals.append({
            'label': time_interval['label'],
            'data': get_bugs(time_interval)
        })
    return data_by_time_intervals


def write_csv(data_by_time_intervals):
    with open('data/firefox_team_regressions_by_severity.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Confirmed bugs set as regressions by week and severity'])
        writer.writerow([])

        writer.writerow([
            '',
        ]
        +
        list(reversed([data_by_time_interval['label'] for data_by_time_interval in data_by_time_intervals]))
        )

        severity_map = {
            "blocker": "S1",
            "critical": "S2",
            "major": "S3",
            "normal": "S3",
            "minor": "S4",
            "trivial": "S4",
            "enhancement": "S4",
            "N/A": "--"
        }

        severity_groups = {
            "S1": "S1",
            "S2": "S2",
            "S3": "S3+S4",
            "S4": "S3+S4",
            "--": "none"
        }

        rows = {
            "S1": [],
            "S2": [],
            "S3+S4": [],
            "none": []
        }

        for pos in range(len(data_by_time_intervals) - 1, -1, -1):
            for row in rows.values():
                row.append([])
            data_by_time_interval = data_by_time_intervals[pos]
            bugs_data = data_by_time_interval["data"]["regressions_added"]
            for bug_data in bugs_data:
                if bug_data["severity"] in severity_map.keys():
                    severity = severity_map[bug_data["severity"]]
                else:
                    severity = bug_data["severity"]
                severity_group = severity_groups[severity]
                rows[severity_group][-1].append(bug_data["id"])

        for key, bug_ids_for_time_intervals in rows.items():
            writer.writerow([key] + [len(bug_ids) for bug_ids in bug_ids_for_time_intervals])

        writer.writerow([])

        for key, bug_ids_for_time_intervals in rows.items():
            writer.writerow([key] + [BUG_LIST_WEB_URL + ",".join(list(map(str, bug_ids))) if bug_ids else "" for bug_ids in bug_ids_for_time_intervals])


parser = argparse.ArgumentParser(description='Count confirmed Firefox bugs set as regressions by development cycle or week')
parser.add_argument('--date-min', type=str,
                    help='Minimum date (format: YYYY-MM-DD) to check')
parser.add_argument('--version-min', type=int,
                    help='Minimum Firefox version to check')
parser.add_argument('--weeks', type=int,
                    help='Number of recent weeks to check')
args = parser.parse_args()

time_intervals = []
if args.date_min:
    try:
        start_day = datetime.date.fromisoformat(args.date_min)
    except:
        sys.exit(f"--date-min argument must be in format YYYY-MM-DD but is {args.date_min}")
    if start_day.weekday() < 6:
        start_sunday = start_day - datetime.timedelta(start_day.weekday() + 1 - 7)
    else:
        start_sunday = start_day
    now = datetime.datetime.utcnow()
    end_sunday = now.date() - datetime.timedelta(now.weekday())
    weeks_count = (end_sunday - start_sunday).days // 7
    for week_nr in range(weeks_count):
        from_sunday = start_sunday + week_nr * datetime.timedelta(7)
        to_sunday = start_sunday + (week_nr + 1) * datetime.timedelta(7)
        time_intervals.append({
            'from': from_sunday,
            'to': to_sunday,
            'label': to_sunday.isoformat(),
        })
elif args.weeks:
    for week_nr in range(args.weeks):
        now = datetime.datetime.utcnow()
        to_sunday = now.date() - datetime.timedelta(now.weekday() + 1 + 7 * week_nr)
        from_sunday = to_sunday - datetime.timedelta(7)
        time_intervals.append({
            'from': from_sunday,
            'to': to_sunday,
            'label': to_sunday.isoformat(),
        })
    time_intervals.reverse()
elif args.version_min:
    releases = productdates.get_latest_nightly_versions_by_min_version(args.version_min)
    for release_pos in range(len(releases)):
        if release_pos == len(releases) - 1:
            end_date = datetime.date.today() + datetime.timedelta(days = 1)
        else:
            end_date = releases[release_pos + 1]['date']
        version = releases[release_pos]['version']
        time_intervals.append({
            'from': releases[release_pos]['date'],
            'to': end_date,
            'label': str(releases[release_pos]['version']),
        })
else:
    sys.exit('No time intervals requested')


data_by_time_intervals = measure_data(time_intervals)
write_csv(data_by_time_intervals)

