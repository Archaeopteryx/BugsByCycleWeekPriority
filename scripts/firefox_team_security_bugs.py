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
from config.firefox_team import PRODUCTS_TO_CHECK, PRODUCTS_COMPONENTS_TO_CHECK

import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

STATUS_OPEN = ['UNCONFIRMED', 'NEW', 'ASSIGNED', 'REOPENED']

def get_security_open(label, start_date, end_date):

    def bug_handler(bug_data):
        if bug_data['id'] in [data['id'] for data in bugs_data]:
            return
        if datetime.datetime.strptime(bug_data["creation_time"], '%Y-%m-%dT%H:%M:%SZ').date() >= end_date:
            return
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "status", "keywords", "groups"], start_date, end_date)
        if [bug_states["product"]["new"], bug_states["component"]["new"]] not in PRODUCTS_COMPONENTS_TO_CHECK:
            return
        if bug_states["status"]["new"] not in STATUS_OPEN:
            return
        if (type(bug_states["groups"]["new"]) == "list" and not any(["security" in group for group in bug_states["groups"]["new"]])) or \
           (type(bug_states["groups"]["new"]) == "str" and not "security" in bug_states["groups"]["new"]):
            return
        if "stalled" in bug_states["keywords"]["new"] :
            return
        bugs_data.append({
          'id': bug_data['id'],
        })

    bugs_data = []

    fields = [
              'id',
              'product',
              'component',
              'status',
              'keywords',
              'groups',
              'creation_time',
              'history',
             ]

    params = {
        'include_fields': fields,
        'f1': 'bug_group',
        'o1': 'substring',
        'v1': 'security',
        'f2': 'bug_status',
        'o2': 'anywords',
        'v2': STATUS_OPEN,
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'f1': 'bug_group',
        'o1': 'substring',
        'v1': 'security',
        'f2': 'bug_status',
        'o2': 'changedafter',
        'v2': start_date,
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'f1': 'bug_group',
        'o1': 'changedafter',
        'v1': start_date,
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    return bugs_data


def get_security_fixed(label, start_date, end_date):

    def bug_handler(bug_data):
        if bug_data['id'] in [data['id'] for data in bugs_data]:
            return
        creation_date = datetime.datetime.strptime(bug_data["creation_time"], '%Y-%m-%dT%H:%M:%SZ').date()
        if creation_date >= end_date:
            return
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "status", "resolution", "keywords", "groups"], start_date, end_date)
        if creation_date < start_date and bug_states["status"]["old"] not in STATUS_OPEN:
            return
        if [bug_states["product"]["new"], bug_states["component"]["new"]] not in PRODUCTS_COMPONENTS_TO_CHECK:
            return
        if bug_states["resolution"]["new"] != "FIXED":
            return
        if not any(["security" in group for group in bug_states["groups"]["new"]]):
            return
        bugs_data.append({
          'id': bug_data['id'],
        })

    bugs_data = []

    fields = [
              'id',
              'product',
              'component',
              'status',
              'resolution',
              'keywords',
              'groups',
              'creation_time',
              'history',
             ]

    params = {
        'include_fields': fields,
        'f1': 'OP',
        'j1': 'AND_G',
        'f2': 'resolution',
        'o2': 'changedto',
        'v2': 'FIXED',
        'f3': 'resolution',
        'o3': 'changedafter',
        'v3': start_date,
        'f4': 'resolution',
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
    data['security_open'] = get_security_open(label, start_date, end_date)
    data['security_fixed'] = get_security_fixed(label, start_date, end_date)

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
    with open('data/firefox_team_security_bugs.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Open and fixed security bugs for Firefox team by week'])
        writer.writerow([])

        writer.writerow([
            '',
        ]
        +
        list(reversed([data_by_time_interval['label'] for data_by_time_interval in data_by_time_intervals]))
        )

        rows = [
            ['open'],
            ['fixed'],
            ['open bugs'],
            ['fixed bugs'],
        ]
        for pos in range(len(data_by_time_intervals) - 1, -1, -1):
            data_by_time_interval = data_by_time_intervals[pos]
            bugs_data_open = data_by_time_interval["data"]["security_open"]
            bugs_data_fixed = data_by_time_interval["data"]["security_fixed"]
            rows[0].append(len(bugs_data_open))
            rows[1].append(len(bugs_data_fixed))
            rows[2].append(BUG_LIST_WEB_URL + ",".join(list(map(str, sorted([bug_data["id"] for bug_data in bugs_data_open])))) if bugs_data_open else "")
            rows[3].append(BUG_LIST_WEB_URL + ",".join(list(map(str, sorted([bug_data["id"] for bug_data in bugs_data_fixed])))) if bugs_data_fixed else "")
        writer.writerows(rows)


parser = argparse.ArgumentParser(description='Count open and fixed security Firefox bugs by development cycle or week')
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

