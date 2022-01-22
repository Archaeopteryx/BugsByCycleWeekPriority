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

BUG_LIST_WEB_URL = 'https://bugzilla.mozilla.org/buglist.cgi?bug_id_type=anyexact&list_id=15921940&query_format=advanced&bug_id='
BUGZILLA_CONFIG_URL = 'https://bugzilla.mozilla.org/rest/configuration'

PRODUCTS_TO_CHECK = [
    'Core',
#    'DevTools',
    'Firefox',
#    'Firefox Build System',
#    'Testing',
    'Toolkit',
#    'WebExtensions',
]

PRODUCTS_COMPONENTS_TO_CHECK = [
    ['Core', 'Window Management'],
    ['Core', 'XUL'],
    ['Firefox', 'Downloads Panel'],
    ['Firefox', 'File Handling'],
    ['Firefox', 'General'],
    ['Firefox', 'Menus'],
    ['Firefox', 'Migration'],
    ['Firefox', 'Preferences'],
    ['Firefox', 'Toolbars and Customization'],
    ['Firefox', 'Tours'],
    ['Toolkit', 'Downloads API'],
    ['Toolkit', 'General'],
    ['Toolkit', 'Notifications and Alerts'],
    ['Toolkit', 'Picture-in-Picture'],
    ['Toolkit', 'Preferences'],
    ['Toolkit', 'Printing'],
    ['Toolkit', 'Reader Mode'],
    ['Toolkit', 'Toolbars and Toolbar Customization'],
    ['Toolkit', 'Video/Audio Controls'],
    ['Toolkit', 'XUL Widgets'],
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
#            if product_name in ['Firefox', 'Toolkit', 'Core']:
#                print(f"{product_name} :: {component_data['name']} --- {component_data['team_name']}")
    return COMPONENT_TO_TEAM

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

def get_created(label, start_date, end_date):

    def bug_handler(bug_data):
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "severity"], start_date, end_date)
        if not bug_states["severity"]["new"] in SEVERITIES:
            return
        if [bug_states["product"]["new"], bug_states["component"]["new"]] in PRODUCTS_COMPONENTS_TO_CHECK:
            bugs_data.append({
              'id': bug_data['id'],
            })
            bugs_table.append([
                bug_data['id'],
                # COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
                bug_data['product'],
                bug_data['component'],
                label,
                'created',
            ])

    fields = [
              'id',
              'product',
              'component',
              'severity',
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
        'f9': 'CP',
        'f10': 'OP',
        'j10': 'AND_G',
        'f11': 'bug_severity',
        'o11': 'changedfrom',
        'v11': 'S2',
        'f12': 'bug_severity',
        'o12': 'changedafter',
        'f15': 'CP',
        'f16': 'bug_severity',
        'o16': 'equals',
        'v16': 'S1',
        'f17': 'bug_severity',
        'o17': 'equals',
        'v17': 'S2',
        'f18': 'CP',
        'f19': 'creation_ts',
        'o19': 'greaterthan',
        'f20': 'creation_ts',
        'o20': 'lessthan',
    }

    params['v6'] = start_date
    params['v12'] = start_date
    params['v19'] = start_date
    params['v20'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_increased(label, start_date, end_date):

    def bug_handler(bug_data):
        if datetime.datetime.strptime(bug_data["creation_time"], '%Y-%m-%dT%H:%M:%SZ').date() < start_date:
            return
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "severity"], start_date, end_date)
        if not (bug_states["severity"]["old"] not in SEVERITIES and bug_states["severity"]["new"] in SEVERITIES):
            return
        if [bug_states["product"]["old"], bug_states["component"]["old"]] in PRODUCTS_COMPONENTS_TO_CHECK and [bug_states["product"]["new"], bug_states["component"]["new"]] in PRODUCTS_COMPONENTS_TO_CHECK:
            bugs_data.append({
              'id': bug_data['id'],
            })
            bugs_table.append([
                bug_data['id'],
                # COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
                bug_data['product'],
                bug_data['component'],
                label,
                'increased',
            ])

    fields = [
              'id',
              'product',
              'component',
              'severity',
              'creation_time',
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
        'o5': 'changedto',
        'v5': 'S1',
        'f6': 'bug_severity',
        'o6': 'changedafter',
        'f7': 'bug_severity',
        'o7': 'changedbefore',
        'f9': 'CP',
        'f10': 'OP',
        'j10': 'AND_G',
        'f11': 'bug_severity',
        'o11': 'changedto',
        'v11': 'S2',
        'f12': 'bug_severity',
        'o12': 'changedafter',
        'f13': 'bug_severity',
        'o13': 'changedbefore',
        'f15': 'CP',
        'f16': 'CP',
        # Using this condition slows the query down and it fails to return data;
        # this requirement gets handled in the `bug_handler` function
        # 'f17': 'creation_ts',
        # 'o17': 'lessthan',
    }

    params['v6'] = start_date
    params['v7'] = end_date
    params['v12'] = start_date
    params['v13'] = end_date
    # See above
    # params['v17'] = start_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_lowered(label, start_date, end_date):

    def bug_handler(bug_data):
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "severity"], start_date, end_date)
        if [bug_states["product"]["new"], bug_states["component"]["new"]] not in PRODUCTS_COMPONENTS_TO_CHECK:
            return
        if bug_states["severity"]["old"] in SEVERITIES and bug_states["severity"]["new"] not in SEVERITIES:
            bugs_data.append({
              'id': bug_data['id'],
            })
            bugs_table.append([
                bug_data['id'],
                # COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
                bug_data['product'],
                bug_data['component'],
                label,
                'lowered',
            ])

    fields = [
              'id',
              'product',
              'component',
              'severity',
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
#        'f7': 'bug_severity',
#        'o7': 'changedbefore',
        'f9': 'CP',
        'f10': 'OP',
        'j10': 'AND_G',
        'f11': 'bug_severity',
        'o11': 'changedfrom',
        'v11': 'S2',
        'f12': 'bug_severity',
        'o12': 'changedafter',
#        'f13': 'bug_severity',
#        'o13': 'changedbefore',
        'f15': 'CP',
        'f16': 'CP',
    }

    params['v6'] = start_date
#    params['v7'] = end_date
    params['v12'] = start_date
#    params['v13'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_fixed(label, start_date, end_date):

    def bug_handler(bug_data):
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "severity", "resolution"], start_date, end_date)
        if [bug_states["product"]["new"], bug_states["component"]["new"]] not in PRODUCTS_COMPONENTS_TO_CHECK:
            return
        if bug_states["severity"]["new"] not in SEVERITIES:
            return
        if bug_states["resolution"]["old"] != 'FIXED' and bug_states["resolution"]["new"] == 'FIXED':
            bugs_data.append({
              'id': bug_data['id'],
            })
            bugs_table.append([
                bug_data['id'],
                # COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
                bug_data['product'],
                bug_data['component'],
                label,
                'fixed',
            ])

    fields = [
              'id',
              'product',
              'component',
              'resolution',
              'severity',
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
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "severity", "resolution"], start_date, end_date)
        if [bug_states["product"]["new"], bug_states["component"]["new"]] not in PRODUCTS_COMPONENTS_TO_CHECK:
            return
        if bug_states["severity"]["new"] not in SEVERITIES:
            return
        if bug_states["resolution"]["old"] == '' and bug_states["resolution"]["new"] not in ['', 'FIXED']:
            bugs_data.append({
              'id': bug_data['id'],
            })
            bugs_table.append([
                bug_data['id'],
                # COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
                bug_data['product'],
                bug_data['component'],
                label,
                'closed',
            ])

    fields = [
              'id',
              'product',
              'component',
              'resolution',
              'severity',
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

def get_moved_to(label, start_date, end_date):

    def bug_handler(bug_data):
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "severity"], start_date, end_date)
        if bug_states["severity"]["new"] not in SEVERITIES:
            return
        if [bug_states["product"]["old"], bug_states["component"]["old"]] not in PRODUCTS_COMPONENTS_TO_CHECK and [bug_states["product"]["new"], bug_states["component"]["new"]] in PRODUCTS_COMPONENTS_TO_CHECK:
            bugs_data.append({
              'id': bug_data['id'],
            })
            bugs_table.append([
                bug_data['id'],
                # COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
                bug_data['product'],
                bug_data['component'],
                label,
                'moved_to',
            ])

    fields = [
              'id',
              'product',
              'component',
              'severity',
              'history',
             ]

    params = {
        'include_fields': fields,
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
        'o5': 'changedto',
        'v5': 'S1',
        'f6': 'bug_severity',
        'o6': 'changedafter',
        'f7': 'bug_severity',
        'o7': 'changedbefore',
        'f9': 'CP',
        'f10': 'OP',
        'j10': 'AND_G',
        'f11': 'bug_severity',
        'o11': 'changedto',
        'v11': 'S2',
        'f12': 'bug_severity',
        'o12': 'changedafter',
        'f13': 'bug_severity',
        'o13': 'changedbefore',
        'f15': 'CP',
        'f16': 'bug_severity',
        'o16': 'equals',
        'v16': 'S1',
        'f17': 'bug_severity',
        'o17': 'equals',
        'v17': 'S2',
        'f18': 'CP',
        'f19': 'OP',
        # The search doesn't supported grouping 'changedafter' and changedbefore'
        # for 'product'.
        'j19': 'AND',
        'f21': 'product',
        'o21': 'changedafter',
        'f22': 'product',
        'o22': 'changedbefore',
        'f23': 'CP',
    }

    params['v21'] = start_date
    params['v22'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_moved_away(label, start_date, end_date):

    def bug_handler(bug_data):
        bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "severity"], start_date, end_date)
        if bug_states["severity"]["old"] not in SEVERITIES:
            return
        if [bug_states["product"]["old"], bug_states["component"]["old"]] in PRODUCTS_COMPONENTS_TO_CHECK and [bug_states["product"]["new"], bug_states["component"]["new"]] not in PRODUCTS_COMPONENTS_TO_CHECK:
            bugs_data.append({
              'id': bug_data['id'],
            })
            bugs_table.append([
                bug_data['id'],
                # COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
                bug_data['product'],
                bug_data['component'],
                label,
                'moved_away',
            ])

    fields = [
              'id',
              'product',
              'component',
              'severity',
              'history',
             ]

    params = {
        'include_fields': fields,
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
        'f16': 'bug_severity',
        'o16': 'equals',
        'v16': 'S1',
        'f17': 'bug_severity',
        'o17': 'equals',
        'v17': 'S2',
        'f18': 'CP',
        'f19': 'OP',
        # The search doesn't supported grouping 'changedafter' and changedbefore'
        # for 'product'.
        'j19': 'AND',
        'f21': 'product',
        'o21': 'changedafter',
        'f22': 'product',
        'o22': 'changedbefore',
        'f23': 'CP',
    }

    params['v21'] = start_date
    params['v22'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    data = [bug_data['id'] for bug_data in bugs_data]

    return data

def get_open(label):

    def bug_handler(bug_data):
        if [bug_data["product"], bug_data["component"]] not in PRODUCTS_COMPONENTS_TO_CHECK:
            return
        bugs_data.append({
          'id': bug_data['id'],
        })
        bugs_table.append([
            bug_data['id'],
            # COMPONENT_TO_TEAM[f"{bug_data['product']} :: {bug_data['component']}"],
            bug_data['product'],
            bug_data['component'],
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
    data['created'] = get_created(label, start_date, end_date)
    data['increased'] = get_increased(label, start_date, end_date)
    data['lowered'] = get_lowered(label, start_date, end_date)
    data['fixed'] = get_fixed(label, start_date, end_date)
    data['closed'] = get_closed_but_not_fixed(label, start_date, end_date)
    data['moved_to'] = get_moved_to(label, start_date, end_date)
    data['moved_away'] = get_moved_away(label, start_date, end_date)

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
            {"key": "created", "value": "S1 or S2 created"},
            {"key": "increased", "value": "S1 or S2 increased"},
            {"key": "lowered", "value": "Lowered below S2"},
            {"key": "fixed", "value": "S1 or S2 fixed"},
            {"key": "closed", "value": "S1 or S2 closed but not fixed (e.g. as duplicate)"},
            {"key": "moved_to", "value": "S1 or S2 moved from uninteresting to interesting products"},
            {"key": "moved_away", "value": "S1 or S2 moved from interesting to uninteresting products"},
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
data_by_time_intervals = measure_data(time_intervals)
open_bugs = get_open(time_intervals[-1]['label'])
write_csv(data_by_time_intervals, open_bugs, bugs_table)

