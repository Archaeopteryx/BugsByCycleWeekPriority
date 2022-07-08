# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This scripts generates a report of bugs which
# * have the severity S1 or S2

import argparse
import csv
import datetime
import json
from libmozdata.bugzilla import Bugzilla
from logger import logger
import productdates
import pytz
import urllib.request

import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

BUGZILLA_CONFIG_URL = 'https://bugzilla.mozilla.org/rest/configuration'

PRODUCTS_TO_CHECK = [
    'Core',
    'DevTools',
    'Firefox',
    'Firefox Build System',
    'Remote Protocol',
#    'Testing',
    'Toolkit',
    'WebExtensions',
]

SEVERITIES = ['S2']

STATUS_OPEN = ['UNCONFIRMED', 'NEW', 'ASSIGNED', 'REOPENED']

def get_relevant_bug_changes(bug_data, fields, start_date, end_date):
    bug_states = {}
    for field in fields:
        bug_states[field] = {
            "old": None,
            "new": None,
        }
    for historyItem in bug_data['history']:
        for change in historyItem['changes']:
            field = change['field_name']
            if field in fields:
                change_time_str = historyItem['when']
                change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                change_time = pytz.utc.localize(change_time).date()
                if change_time < start_date:
                    bug_states[field]["old"] = change['added']
                elif start_date <= change_time < end_date:
                    if bug_states[field]["old"] is None:
                        bug_states[field]["old"] = change['removed']
                    bug_states[field]["new"] = change['added']
                if change_time > end_date:
                    if bug_states[field]["old"] is None:
                        bug_states[field]["old"] = change['removed']
                    if bug_states[field]["new"] is None:
                        bug_states[field]["new"] = change['removed']
    for field in fields:
        if bug_states[field]["old"] is None:
            bug_states[field]["old"] = bug_data[field]
        if bug_states[field]["new"] is None:
            bug_states[field]["new"] = bug_data[field]
    return bug_states

def get_severity_start_and_resolved(bug_data):
    severity_start = None
    last_resolved = None
    for historyItem in bug_data['history']:
        for change in historyItem['changes']:
            change_time_str = historyItem['when']
            change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
            change_time = pytz.utc.localize(change_time).date()
            field = change['field_name']
            if field == 'severity':
                severity_old = change['removed']
                severity_new = change['added']
                if severity_start is None and severity_new in ['S1', 'S2']:
                    severity_start = change_time
                elif severity_new not in ['S1', 'S2']:
                    severity_start = None
            elif field == 'cf_last_resolved':
                last_resolved = change_time
    if severity_start is None:
        creation_time = datetime.datetime.strptime(bug_data['creation_time'], '%Y-%m-%dT%H:%M:%SZ')
        creation_time = pytz.utc.localize(creation_time).date()
        severity_start = creation_time
    if bug_data['status'] in STATUS_OPEN:
        last_resolved = None
    return [severity_start, last_resolved]

def get_bugs(time_intervals):

    def bug_handler(bug_data):
        creation_time = datetime.datetime.strptime(bug_data['creation_time'], '%Y-%m-%dT%H:%M:%SZ')
        creation_time = pytz.utc.localize(creation_time).date()
        for time_interval in time_intervals:
            start_date = time_interval['from']
            end_date = time_interval['to']
            date_label = time_interval['label']
            if creation_time >= end_date:
                continue
            # [severity_start, last_resolved] = get_severity_start_and_resolved(bug_data)
            bug_states = get_relevant_bug_changes(bug_data, ["product", "severity", "status", "resolution"], start_date, end_date)
            if bug_states["severity"]["new"] not in SEVERITIES:
                continue
            if bug_states["product"]["new"] not in PRODUCTS_TO_CHECK:
                continue
            if bug_states["status"]["new"] in STATUS_OPEN:
                if bug_data['id'] not in bugs_by_date[date_label]:
                    bugs_by_date[date_label].append(bug_data['id'])
            if bug_states["status"]["old"] in STATUS_OPEN and bug_states["resolution"]["new"] == "FIXED":
                if bug_data['id'] not in fixed_bugs_by_date[date_label]:
                    fixed_bugs_by_date[date_label].append(bug_data['id'])
                if creation_time < start_date:
                    if bug_data['id'] not in fixed_old_bugs_by_date[date_label]:
                        fixed_old_bugs_by_date[date_label].append(bug_data['id'])

    start_date = time_intervals[0]['from']

    bugs_by_date = {}
    fixed_bugs_by_date = {}
    fixed_old_bugs_by_date = {}
    for data_series in [bugs_by_date, fixed_bugs_by_date, fixed_old_bugs_by_date]:
        for time_interval in time_intervals:
            date_label = time_interval['to'].isoformat()
            data_series[time_interval['label']] = []

    fields = [
              'id',
              'product',
              'status',
              'resolution',
              'severity',
              'creation_time',
              'history',
             ]

    params = {
        'include_fields': fields,
        'bug_severity': SEVERITIES,
        'f1': 'keywords',
        'o1': 'allwords',
        'v1': 'regression',
        'f2': 'bug_status',
        'o2': 'anywords',
        'v2': STATUS_OPEN,
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'bug_severity': SEVERITIES,
        'f1': 'keywords',
        'o1': 'allwords',
        'v1': 'regression',
        'f2': 'cf_last_resolved',
        'o2': 'changedafter',
    }

    params['v2'] = start_date

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'f1': 'keywords',
        'o1': 'allwords',
        'v1': 'regression',
        'f2': 'OP',
        'j2': 'AND_G',
        'f3': 'bug_severity',
        'o3': 'changedfrom',
        'v3': 'S2',
        'f4': 'bug_severity',
        'o4': 'changedafter',
        'f5': 'CP',
    }

    params['v4'] = start_date

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    open_bug_count_by_day = []
    bugs_by_date_list = sorted([{key: value} for key, value in bugs_by_date.items()], key = lambda item: list(item.keys())[0])
    for bugs_for_single_day_dict in bugs_by_date_list:
        key = list(bugs_for_single_day_dict.keys())[0]
        open_bug_count_by_day.append({key: bugs_for_single_day_dict[key]})

    fixed_bug_count_by_day = []
    bugs_by_date_list = sorted([{key: value} for key, value in fixed_bugs_by_date.items()], key = lambda item: list(item.keys())[0])
    for bugs_for_single_day_dict in bugs_by_date_list:
        key = list(bugs_for_single_day_dict.keys())[0]
        fixed_bug_count_by_day.append({key: bugs_for_single_day_dict[key]})

    fixed_old_bug_count_by_day = []
    bugs_by_date_list = sorted([{key: value} for key, value in fixed_old_bugs_by_date.items()], key = lambda item: list(item.keys())[0])
    for bugs_for_single_day_dict in bugs_by_date_list:
        key = list(bugs_for_single_day_dict.keys())[0]
        fixed_old_bug_count_by_day.append({key: bugs_for_single_day_dict[key]})

    return open_bug_count_by_day, fixed_bug_count_by_day, fixed_old_bug_count_by_day

def write_csv(open_bug_count_by_day, fixed_bug_count_by_day, fixed_old_bug_count_by_day):
    with open('data/s2_opened_closed_velocity.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Bugs with severity S2'])
        writer.writerow([])

        row = ['date'] + [list(day_data.keys())[0] for day_data in open_bug_count_by_day]
        writer.writerow(row)

        row = ['open'] + [len(list(day_data.values())[0]) for day_data in open_bug_count_by_day]
        writer.writerow(row)

        row = ['fixed'] + [len(list(day_data.values())[0]) for day_data in fixed_bug_count_by_day]
        writer.writerow(row)

        row = ['fixed, bug with S2 before this week'] + [len(list(day_data.values())[0]) for day_data in fixed_old_bug_count_by_day]
        writer.writerow(row)

        writer.writerow([])

        writer.writerow(['Date', 'Bug ID'])
        for day_data in open_bug_count_by_day:
            for bug_id in sorted(list(day_data.values())[0]):
                writer.writerow([list(day_data.keys())[0]] + [bug_id])

parser = argparse.ArgumentParser(description='Count open, opened and closed Firefox bugs with severity S1 or S2 by developmen cycle or week')
parser.add_argument('--start-date', type=str,
                    help='Bug must have had activity on this day or later (YYYY-MM-DD)')
parser.add_argument('--debug',
                    action='store_true',
                    help='Show debug information')
args = parser.parse_args()
debug = args.debug

# Close to date when 'S<number>' severities replaced 'major', 'minor' etc.
start_date = args.start_date if args.start_date else '2022-01-02'

start_day = datetime.datetime.strptime(start_date, '%Y-%m-%d')

time_intervals = []
# First Sunday of the year
from_day = start_day - datetime.timedelta(7)
day_max = min(datetime.datetime(2022, 7, 1), datetime.datetime.now())
while from_day < day_max:
    to_day = from_day + datetime.timedelta(7)
    time_intervals.append({
        'from': from_day.date(),
        'to': to_day.date(),
        'label': to_day.date().isoformat(),
    })
    from_day += datetime.timedelta(7)
# time_intervals.reverse()

open_bug_count_by_day, fixed_bug_count_by_day, fixed_old_bug_count_by_day = get_bugs(time_intervals)
write_csv(open_bug_count_by_day, fixed_bug_count_by_day, fixed_old_bug_count_by_day)

