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

BUG_LIST_WEB_URL = 'https://bugzilla.mozilla.org/buglist.cgi?bug_id_type=anyexact&list_id=15921940&query_format=advanced&bug_id='
BUGZILLA_CONFIG_URL = 'https://bugzilla.mozilla.org/rest/configuration'

PRODUCTS_TO_CHECK = [
#    'Core',
#    'DevTools',
    'Firefox',
#    'Firefox Build System',
#    'Testing',
#    'Toolkit',
#    'WebExtensions',
]

SEVERITIES = ['S1', 'S2']

STATUS_OPEN = ['UNCONFIRMED', 'NEW', 'ASSIGNED', 'REOPENED']
STATUS_UNAFFECTED = ['unaffected']
STATUS_UNKNOWN = ['---']

# Holds all bugs, used for pivot table
bugs_table = []

def get_component_to_team():
    with urllib.request.urlopen(BUGZILLA_CONFIG_URL) as request_handle:
        data = json.loads(request_handle.read())

        ID_TO_PRODUCT = {}
        products_data = data['field']['product']['values']
        for pos in range(len(products_data)):
            if products_data[pos]['isactive'] == 0:
                continue

            product_name = products_data[pos]['name']
            if product_name not in PRODUCTS_TO_CHECK:
                continue

            ID_TO_PRODUCT[products_data[pos]['id']] = product_name

        COMPONENT_TO_TEAM = {}
        components_data = data['field']['component']['values']
        for component_data in components_data:
            if component_data['isactive'] == 0:
                continue

            if component_data['product_id'] not in ID_TO_PRODUCT.keys():
                continue

            product_name = ID_TO_PRODUCT[component_data['product_id']]
            COMPONENT_TO_TEAM[f"{product_name} :: {component_data['name']}"] = component_data['team_name']
    return COMPONENT_TO_TEAM

def get_added(label, start_date, end_date):

    def bug_handler(bug_data):
        historyProcessed = False
        for historyItem in bug_data['history']:
            for change in historyItem['changes']:
                if change['field_name'] == 'severity':
                    change_time_str = historyItem['when']
                    change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                    change_time = pytz.utc.localize(change_time).date()
                    if change_time < start_date:
                        continue
                    if change_time > end_date:
                        historyProcessed = True
                        break
                    severity_old = change['removed']
                    severity_new = change['added']
                    if severity_old not in SEVERITIES and severity_new in SEVERITIES:
                        bugs_data.append({
                          'id': bug_data['id'],
                        })
                        bugs_table.append([
                            bug_data['id'],
                            COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
                            label,
                            'added',
                        ])
                        historyProcessed = True
            if historyProcessed:
                break

    fields = [
              'id',
              'product',
              'component',
              'history',
             ]

    params = {
        'include_fields': fields,
        'product': PRODUCTS_TO_CHECK,
        'f1': 'bug_group',
        'o1': 'notsubstring',
        'v1': 'security',
        'f2': 'keywords',
        'o2': 'nowords',
        'v2': 'crash',
        'f3': 'OP',
        'j3': 'OR',
        'f4': 'OP',
        'f5': 'bug_severity',
        'o5': 'changedto',
        'v5': 'S1',
        'f6': 'bug_severity',
        'o6': 'changedafter',
        'f7': 'bug_severity',
        'o7': 'changedbefore',
        'f9': 'CP',
        'f10': 'OP',
        'f11': 'bug_severity',
        'o11': 'changedto',
        'v11': 'S2',
        'f12': 'bug_severity',
        'o12': 'changedafter',
        'f13': 'bug_severity',
        'o13': 'changedbefore',
        'f15': 'CP',
        'f16': 'CP',
    }

    params['v6'] = start_date
    params['v7'] = end_date
    params['v12'] = start_date
    params['v13'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_lowered(label, start_date, end_date):

    def bug_handler(bug_data):
        historyProcessed = False
        for historyItem in bug_data['history']:
            for change in historyItem['changes']:
                if change['field_name'] == 'severity':
                    change_time_str = historyItem['when']
                    change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                    change_time = pytz.utc.localize(change_time).date()
                    if change_time < start_date:
                        continue
                    if change_time > end_date:
                        historyProcessed = True
                        break
                    severity_old = change['removed']
                    severity_new = change['added']
                    if severity_old not in SEVERITIES and severity_new in SEVERITIES:
                        bugs_data.append({
                          'id': bug_data['id'],
                        })
                        bugs_table.append([
                            bug_data['id'],
                            COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
                            label,
                            'lowered',
                        ])
                        historyProcessed = True
            if historyProcessed:
                break

    fields = [
              'id',
              'product',
              'component',
              'history',
             ]

    params = {
        'include_fields': fields,
        'product': PRODUCTS_TO_CHECK,
        'f1': 'bug_group',
        'o1': 'notsubstring',
        'v1': 'security',
        'f2': 'keywords',
        'o2': 'nowords',
        'v2': 'crash',
        'f3': 'OP',
        'j3': 'OR',
        'f4': 'OP',
        'j4': 'AND_G',
        'f5': 'bug_severity',
        'o5': 'changedfrom',
        'v5': 'S1',
        'f6': 'bug_severity',
        'o6': 'changedafter',
        'f7': 'bug_severity',
        'o7': 'changedbefore',
        'f9': 'CP',
        'f10': 'OP',
        'j10': 'AND_G',
        'f11': 'bug_severity',
        'o11': 'changedfrom',
        'v11': 'S2',
        'f12': 'bug_severity',
        'o12': 'changedafter',
        'f13': 'bug_severity',
        'o13': 'changedbefore',
        'f15': 'CP',
        'f16': 'CP',
    }

    params['v6'] = start_date
    params['v7'] = end_date
    params['v12'] = start_date
    params['v13'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_fixed(label, start_date, end_date):

    def bug_handler(bug_data):
        bugs_data.append({
          'id': bug_data['id'],
        })
        bugs_table.append([
            bug_data['id'],
            COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
            label,
            'fixed',
        ])

    fields = [
              'id',
              'product',
              'component',
             ]

    params = {
        'include_fields': fields,
        'product': PRODUCTS_TO_CHECK,
        'f1': 'bug_group',
        'o1': 'notsubstring',
        'v1': 'security',
        'f2': 'keywords',
        'o2': 'nowords',
        'v2': 'crash',
        'f3': 'OP',
        'j3': 'OR',
        'f4': 'bug_severity',
        'o4': 'equals',
        'v4': 'S1',
        'f5': 'bug_severity',
        'o5': 'equals',
        'v5': 'S2',
        'f6': 'CP',
        'j7': 'OR',
        'f8': 'OP',
        'j8': 'AND_G',
        'f9': 'resolution',
        'o9': 'changedto',
        'v9': 'FIXED',
        'f10': 'resolution',
        'o10': 'changedafter',
        'f11': 'resolution',
        'o11': 'changedbefore',
        'f12': 'CP',
    }

    params['v10'] = start_date
    params['v11'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_closed_but_not_fixed(label, start_date, end_date):

    def bug_handler(bug_data):
        bugs_data.append({
          'id': bug_data['id'],
        })
        bugs_table.append([
            bug_data['id'],
            COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
            label,
            'closed',
        ])

    fields = [
              'id',
              'product',
              'component',
             ]

    params = {
        'include_fields': fields,
        'product': PRODUCTS_TO_CHECK,
        'f1': 'bug_group',
        'o1': 'notsubstring',
        'v1': 'security',
        'f2': 'keywords',
        'o2': 'nowords',
        'v2': 'crash',
        'f3': 'OP',
        'j3': 'OR',
        'f4': 'bug_severity',
        'o4': 'equals',
        'v4': 'S1',
        'f5': 'bug_severity',
        'o5': 'equals',
        'v5': 'S2',
        'f6': 'CP',
        'f7': 'resolution',
        'o7': 'notequals',
        'v7': 'FIXED',
        'f8': 'OP',
        'j8': 'AND_G',
        'f9': 'bug_status',
        'o9': 'changedto',
        'v9': 'RESOLVED',
        'f10': 'bug_status',
        'o10': 'changedafter',
        'f11': 'bug_status',
        'o11': 'changedbefore',
        'f12': 'CP',
        'f13': 'creation_ts',
        'o13': 'greaterthan',
    }

    params['v13'] = start_date - datetime.timedelta(365)

    params['v10'] = start_date
    params['v11'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_open(label):

    def bug_handler(bug_data):
        bugs_data.append({
          'id': bug_data['id'],
        })
        bugs_table.append([
            bug_data['id'],
            COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
            label,
            'open',
        ])

    fields = [
              'id',
              'product',
              'component',
             ]

    params = {
        'include_fields': fields,
        'product': PRODUCTS_TO_CHECK,
        'bug_status': STATUS_OPEN,
        'severity': SEVERITIES,
    }

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_bugs(time_interval):

    start_date = time_interval['from']
    end_date = time_interval['to']
    label = time_interval['label']
    data = {}
    data['added'] = get_added(label, start_date, end_date)
    data['lowered'] = get_lowered(label, start_date, end_date)
    data['fixed'] = get_fixed(label, start_date, end_date)
    data['closed'] = get_closed_but_not_fixed(label, start_date, end_date)

    print("label:", label)
    print("data:", data)

    return data

def log(message):
    print(message)

def measure_data(time_intervals):
    data_by_time_intervals = []
    for time_interval in time_intervals:
        data_by_time_intervals.append({
            'label': time_interval['label'],
            'data': get_bugs(time_interval)
        })
    return data_by_time_intervals

def write_csv(data_by_time_intervals, open_bugs, bugs_table):
    with open('data/firefox_team_s1_s2.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Bugs with severities S1 or S2: changes by development cycle'])
        writer.writerow([])

        writer.writerow([
            '',
        ]
        +
        list(reversed([data_by_time_interval['label'] for data_by_time_interval in data_by_time_intervals]))
        )

        row_types = [
            {"key": "added", "value": "S1 or S2 added"},
            {"key": "lowered", "value": "Lowered below S2"},
            {"key": "fixed", "value": "S1 or S2 fixed"},
            {"key": "closed", "value": "S1 or S2 closed but not fixed (e.g. as duplicate)"},
        ]

        for row_type in row_types:
            key = row_type["key"]
            value = row_type["value"]
            row = [value]
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                row.append(len(data[key]))
            writer.writerow(row)

        writer.writerow([
            "S1 or S2 open",
            len(open_bugs),
        ])

        writer.writerow([])

        writer.writerow([
            '',
        ]
        +
        list(reversed([data_by_time_interval['label'] for data_by_time_interval in data_by_time_intervals]))
        )

        for row_type in row_types:
            key = row_type["key"]
            value = row_type["value"]
            row = [value]
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                row.append(BUG_LIST_WEB_URL + ','.join([str(bug_id) for bug_id in data[key]]))
            writer.writerow(row)

        writer.writerow([
            "S1 or S2 open",
            BUG_LIST_WEB_URL + ','.join([str(bug_id) for bug_id in open_bugs]),
        ])

        writer.writerow([])
        writer.writerow([])

        for bug_row in bugs_table:
            writer.writerow(bug_row)

parser = argparse.ArgumentParser(description='Count open, opened and closed Firefox bugs with severity S1 or S2 by developmen cycle or week')
parser.add_argument('--version-min', type=int,
                    help='Minimum Firefox version to check')
parser.add_argument('--weeks', type=int,
                    help='Number of recent weeks to check')
parser.add_argument('--debug',
                    action='store_true',
                    help='Show debug information')
args = parser.parse_args()
debug = args.debug

COMPONENT_TO_TEAM = get_component_to_team()

time_intervals = []
if args.weeks:
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
    import sys
    sys.exit('No time intervals requested')
print("time_intervals:", time_intervals)
data_by_time_intervals = measure_data(time_intervals)
open_bugs = get_open(time_intervals[-1]['label'])
write_csv(data_by_time_intervals, open_bugs, bugs_table)

