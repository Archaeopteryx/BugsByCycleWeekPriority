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

def get_bugs(start_date):

    def bug_handler(bug_data):
        [severity_start, last_resolved] = get_severity_start_and_resolved(bug_data)
        if last_resolved and severity_start > last_resolved:
            return
        bugs_data.append([
            bug_data['id'],
            severity_start,
            last_resolved,
        ])

    fields = [
              'id',
              'status',
              'creation_time',
              'cf_last_resolved',
              'history',
             ]

    params = {
        'include_fields': fields,
        'product': PRODUCTS_TO_CHECK,
        'bug_severity': SEVERITIES,
        'f1': 'keywords',
        'o1': 'allwords',
        'v1': 'regression',
        'f1': 'OP',
        'j1': 'OR',
        'f2': 'bug_status',
        'v2': STATUS_OPEN,
        'o2': 'anywords',
        'f3': 'delta_ts',
        'o3': 'greaterthan',
        'v3': '2020-05-01',
        'f4': 'CP',
        'f5': 'keywords',
        'o5': 'allwords',
        'v5': 'regression',
    }

    params['v3'] = start_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    bugs_data.sort(key = lambda bug_data: bug_data[0])

    return bugs_data

def measure_data(time_intervals):
    for time_interval in time_intervals:
        data_by_time_intervals.append({
            'label': time_interval['label'],
            'data': get_bugs(time_interval)
        })
    return data_by_time_intervals

def write_csv(bug_data):
    with open('data/s2_opened_closed_velocity.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Bugs with severity S2'])
        writer.writerow([])

        writer.writerow([
          'id',
          'severity_start',
          'last_resolved',
        ])

        for bug_row in bug_data:
            writer.writerow(bug_row)

parser = argparse.ArgumentParser(description='Count open, opened and closed Firefox bugs with severity S1 or S2 by developmen cycle or week')
parser.add_argument('--start-date', type=str,
                    help='Bug must have had activity on this day or later (YYYY-MM-DD)')
parser.add_argument('--debug',
                    action='store_true',
                    help='Show debug information')
args = parser.parse_args()
debug = args.debug

# Close to date when 'S<number>' severities replaced 'major', 'minor' etc.
start_date = args.start_date if args.start_date else '2020-05-01'

bugs_data = get_bugs(start_date)
write_csv(bugs_data)

