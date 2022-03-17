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
import re
import urllib.request

import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

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

def get_bugs(time_intervals):

    def bug_handler(bug_data):
        creation_time = datetime.datetime.strptime(bug_data['creation_time'], '%Y-%m-%dT%H:%M:%SZ')
        creation_time = pytz.utc.localize(creation_time).date()
        for time_interval in time_intervals:
            date_label = time_interval['label']
            start_date = time_interval['from']
            end_date = time_interval['to']
            if creation_time >= end_date:
                continue
            # [severity_start, last_resolved] = get_severity_start_and_resolved(bug_data)
            bug_states = get_relevant_bug_changes(bug_data, ["product", "severity", "status", "whiteboard"], start_date, end_date)
            if bug_states["product"]["new"] not in PRODUCTS_TO_CHECK:
                continue
            if bug_states["status"]["new"] not in STATUS_OPEN:
                continue
            match = re.search('(?<=access-s)\d+(?=[^\d])', bug_states['whiteboard']['new'])
            if not match:
                continue
            severity_access = 'S' + match.group(0)
            if severity_access != bug_states["severity"]["new"]:
                date_label = time_interval['label']
                if bug_data['id'] not in bugs_by_date[date_label]:
                    bugs_by_date[date_label].append(bug_data['id'])

    start_date = time_intervals[0]['from']

    bugs_by_date = {}
    for time_interval in time_intervals:
        date_label = time_interval['to'].isoformat()
        bugs_by_date[time_interval['label']] = []

    fields = [
              'id',
              'product',
              'severity',
              'status',
              'whiteboard',
              'creation_time',
              'history',
             ]

    params = {
        'include_fields': fields,
        # 'bug_status': STATUS_OPEN,
        'bug_type': 'defect',
        'status_whiteboard': 'access-s',
        'status_whiteboard_type':  'allwordssubstr'
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'bug_type': 'defect',
        'status_whiteboard': 'access-s',
        'status_whiteboard_type':  'allwordssubstr',
        'f1': 'status_whiteboard',
        'o1': 'changedafter',
    }

    params['v2'] = start_date

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'bug_type': 'defect',
        'f1': 'status_whiteboard',
        'o1': 'changedafter',
    }

    params['v1'] = start_date

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    open_bug_count_by_day = []
    bugs_by_date_list = sorted([{key: value} for key, value in bugs_by_date.items()], key = lambda item: list(item.keys())[0])
    for bugs_for_single_day_dict in bugs_by_date_list:
        key = list(bugs_for_single_day_dict.keys())[0]
        open_bug_count_by_day.append({key: len(bugs_for_single_day_dict[key])})
    return open_bug_count_by_day

def measure_data(time_intervals):
    for time_interval in time_intervals:
        data_by_time_intervals.append({
            'label': time_interval['label'],
            'data': get_bugs(time_interval)
        })
    return data_by_time_intervals

def write_csv(bug_data):
    with open('data/access_severity.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(["Open bugs for which access severity and bug's severity doesn't match"])
        writer.writerow([])

        row = ['date'] + [list(day_data.keys())[0] for day_data in bug_data]
        writer.writerow(row)

        row = ['bug_count'] + [list(day_data.values())[0] for day_data in bug_data]
        writer.writerow(row)


parser = argparse.ArgumentParser(description="Count open Firefox bugs with accessibility severity different from bug's severity")
parser.add_argument('--start-date', type=str,
                    help='Start date for measuring data (YYYY-MM-DD)')
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

bugs_data = get_bugs(time_intervals)
write_csv(bugs_data)

