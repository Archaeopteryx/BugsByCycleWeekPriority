# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This scripts generates a report of open bugs in the product 'Core' with the
# severity S2.

import csv
import datetime
import json
from libmozdata.bugzilla import Bugzilla
from logger import logger
import pytz
import urllib.request

from utils.bugzilla import BUG_LIST_WEB_URL, get_component_to_team, get_relevant_bug_changes

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
    'Web Compatibility',
]

PRODUCTS_COMPONENTS_TO_INCLUDE = [
    { 'product': 'Fenix', 'component': 'Browser Engine', },
    { 'product': 'Firefox', 'component': 'Disability Access', },
    { 'product': 'Firefox', 'component': 'PDF Viewer', },
    { 'product': 'Firefox', 'component': 'Translations', },
]

PRODUCTS_COMPONENTS_TO_EXCLUDE = [
    # { 'product': 'Firefox', 'component': 'Address Bar', },
]

SEVERITIES = ['s1', 'S1', 's2', 'S2']

STATUS_OPEN = ['UNCONFIRMED', 'NEW', 'ASSIGNED', 'REOPENED']

MEASURE_START = '2024-01-01'

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
            bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "cf_accessibility_severity", "status", "resolution", "op_sys", "keywords"], start_date, end_date)
            if bug_states["cf_accessibility_severity"]["new"] not in SEVERITIES:
                continue
            if bug_states["product"]["new"] not in PRODUCTS_TO_CHECK:
                is_component_to_include = False
                for product_component_to_check in PRODUCTS_COMPONENTS_TO_INCLUDE:
                    if product_component_to_check["product"] == bug_states["product"]["new"] and product_component_to_check['component'] == bug_states["component"]["new"]:
                        is_component_to_include = True
                if not is_component_to_include:
                    continue
            else:
                is_component_to_include = True
                for product_component_to_check in PRODUCTS_COMPONENTS_TO_EXCLUDE:
                    if product_component_to_check["product"] == bug_states["product"]["new"] and product_component_to_check['component'] == bug_states["component"]["new"]:
                        is_component_to_include = False
                if not is_component_to_include:
                    continue
            if "stalled" in bug_states["keywords"]["new"]:
                continue
            if set(["meta", "sec-high", "sec-critical"]) & set(bug_states["keywords"]["new"]):
                continue
            team = get_component_to_team(bug_states["product"]["new"], bug_states["component"]["new"]) or "Unknown"
            if team not in teams:
                teams.add(team)
            if bug_states["status"]["new"] in STATUS_OPEN:
                if bug_data['id'] not in bugs_by_date[date_label]:
                    bugs_by_date[date_label][bug_data['id']] = {
                        "team": team,
                        "os": bug_states["op_sys"]["new"],
                        "cf_accessibility_severity": bug_states["cf_accessibility_severity"]["new"],
                    }
            if bug_states["status"]["old"] in STATUS_OPEN and bug_states["resolution"]["new"] == "FIXED":
                if bug_data['id'] not in fixed_bugs_by_date[date_label]:
                    fixed_bugs_by_date[date_label][bug_data['id']] = {
                        "team": team,
                        "os": bug_states["op_sys"]["new"],
                    }

    teams = set()

    bugs_by_date = {}
    fixed_bugs_by_date = {}
    for data_series in [bugs_by_date, fixed_bugs_by_date]:
        for time_interval in time_intervals:
            date_label = time_interval['to'].isoformat()
            data_series[time_interval['label']] = {}

    fields = [
              'id',
              'product',
              'component',
              'status',
              'resolution',
              'cf_accessibility_severity',
              'creation_time',
              'op_sys',
              'keywords',
              'history',
             ]

    params = {
        'include_fields': fields,
        'f1': 'cf_accessibility_severity',
        'o1': 'anyexact',
        'v1': SEVERITIES,
        'f2': 'bug_status',
        'o2': 'anyexact',
        'v2': STATUS_OPEN,
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'f1': 'cf_accessibility_severity',
        'o1': 'anyexact',
        'v1': SEVERITIES,
        'f2': 'delta_ts',
        'o2': 'greaterthan',
        'v2': MEASURE_START,
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    for severity in SEVERITIES:
        params = {
            'include_fields': fields,
            'j_top': 'AND_G',
            'f1': 'cf_accessibility_severity',
            'o1': 'changedfrom',
            'v1': severity,
            'f2': 'cf_accessibility_severity',
            'o2': 'changedafter',
            'v2': MEASURE_START,
        }

        Bugzilla(params,
                 bughandler=bug_handler,
                 timeout=960).get_data().wait()

    teams = sorted(list(teams))
    open_bugs_by_day_and_team = []
    bugs_by_date_list = sorted([{key: value} for key, value in bugs_by_date.items()], key = lambda item: list(item.keys())[0])
    for bugs_for_single_day_dict in bugs_by_date_list:
        date = list(bugs_for_single_day_dict.keys())[0]
        open_bugs_for_day_by_team = {}
        for team in teams:
            open_bugs_for_day_by_team[team] = []
        open_bugs = bugs_for_single_day_dict[date]
        for bug_id, bug_data in open_bugs.items():
            team = bug_data["team"]
            open_bugs_for_day_by_team[team].append(bug_id)
        open_bugs_by_day_and_team.append({
            "date": date,
            "teams": open_bugs_for_day_by_team
        })

    open_s1_bugs_by_day = []
    bugs_by_date_list = sorted([{key: value} for key, value in bugs_by_date.items()], key = lambda item: list(item.keys())[0])
    for bugs_for_single_day_dict in bugs_by_date_list:
        date = list(bugs_for_single_day_dict.keys())[0]
        open_bugs_for_day = []
        open_bugs = bugs_for_single_day_dict[date]
        for bug_id, bug_data in open_bugs.items():
            if bug_data["cf_accessibility_severity"] == "s1":
                open_bugs_for_day.append(bug_id)
        open_s1_bugs_by_day.append({
            "date": date,
            "bugs": open_bugs_for_day
        })

    operating_systems = ('All OS', 'Linux', 'macOS', 'Windows', 'Android', 'Other/Unknown')
    open_bugs_by_day_and_os = []
    bugs_by_date_list = sorted([{key: value} for key, value in bugs_by_date.items()], key = lambda item: list(item.keys())[0])
    for bugs_for_single_day_dict in bugs_by_date_list:
        date = list(bugs_for_single_day_dict.keys())[0]
        open_bugs_for_day_by_os = {}
        for operating_system in operating_systems:
            open_bugs_for_day_by_os[operating_system] = []
        open_bugs = bugs_for_single_day_dict[date]
        for bug_id, bug_data in open_bugs.items():
            operating_system = bug_data["os"]
            if operating_system.startswith('Windows'):
                operating_system = 'Windows'
            elif operating_system.startswith('Unspecified'):
                operating_system = 'All'
            if operating_system.startswith('All'):
                operating_system = 'All OS'
            if operating_system not in operating_systems:
                operating_system = 'Other/Unknown'
            open_bugs_for_day_by_os[operating_system].append(bug_id)
        open_bugs_by_day_and_os.append({
            "date": date,
            "os": open_bugs_for_day_by_os
        })

    fixed_bug_count_by_day = []
    bugs_by_date_list = sorted([{key: value} for key, value in fixed_bugs_by_date.items()], key = lambda item: list(item.keys())[0])
    for bugs_for_single_day_dict in bugs_by_date_list:
        key = list(bugs_for_single_day_dict.keys())[0]
        fixed_bug_count_by_day.append({key: bugs_for_single_day_dict[key]})

    return open_bugs_by_day_and_team, open_s1_bugs_by_day, open_bugs_by_day_and_os, fixed_bug_count_by_day

def write_csv(open_bugs_by_day_and_team, open_s1_bugs_by_day, open_bugs_by_day_and_os, fixed_bug_count_by_day):
    with open('data/accessibility_open_s1_s2.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Open Core bugs with accessibility severity S1 or S2'])
        writer.writerow([])

        row = ['date'] + [day_data["date"] for day_data in open_bugs_by_day_and_team]
        writer.writerow(row)

        row = ['open']
        for day_data in open_bugs_by_day_and_team:
            row.append(sum([len(bugs_for_team) for bugs_for_team in day_data["teams"].values()]))
        writer.writerow(row)
        row = ['bugs']
        for day_data in open_bugs_by_day_and_team:
            bugs = []
            for bugs_for_team in day_data["teams"].values():
                bugs.extend(bugs_for_team)
            row.append(BUG_LIST_WEB_URL + ",".join(list(map(str, sorted(bugs)))))
        writer.writerow(row)

        row = ['open s1']
        for bugs_for_day in open_s1_bugs_by_day:
            row.append(len(bugs_for_day["bugs"]))
        writer.writerow(row)
        row = ['bugs s1']
        for bugs_for_day in open_s1_bugs_by_day:
            row.append(BUG_LIST_WEB_URL + ",".join(list(map(str, sorted(bugs_for_day["bugs"])))))
        writer.writerow(row)

        row = ['fixed'] + [len(list(day_data.values())[0]) for day_data in fixed_bug_count_by_day]
        writer.writerow(row)

        writer.writerow([])

        row = ['date'] + [day_data["date"] for day_data in open_bugs_by_day_and_os]
        writer.writerow(row)

        operating_systems = open_bugs_by_day_and_os[0]["os"].keys()
        for operating_system in operating_systems:
            row = [operating_system] + [len(day_data["os"][operating_system]) for day_data in open_bugs_by_day_and_os]
            writer.writerow(row)

        writer.writerow([])

        row = ['date'] + [day_data["date"] for day_data in open_bugs_by_day_and_os]
        writer.writerow(row)

        teams = sorted(open_bugs_by_day_and_os[0]["os"].keys())
        for operating_system in operating_systems:
            row = [operating_system] + [BUG_LIST_WEB_URL + ",".join(list(map(str, sorted(day_data["os"][operating_system])))) for day_data in open_bugs_by_day_and_os]
            writer.writerow(row)

        writer.writerow([])

        row = ['date'] + [day_data["date"] for day_data in open_bugs_by_day_and_team]
        writer.writerow(row)

        teams = sorted(open_bugs_by_day_and_team[0]["teams"].keys())
        for team in teams:
            row = [team] + [len(day_data["teams"][team]) for day_data in open_bugs_by_day_and_team]
            writer.writerow(row)

        writer.writerow([])

        row = ['date'] + [day_data["date"] for day_data in open_bugs_by_day_and_team]
        writer.writerow(row)

        teams = sorted(open_bugs_by_day_and_team[0]["teams"].keys())
        for team in teams:
            row = [team] + [BUG_LIST_WEB_URL + ",".join(list(map(str, sorted(day_data["teams"][team])))) for day_data in open_bugs_by_day_and_team]
            writer.writerow(row)


start_day = datetime.datetime.strptime(MEASURE_START, '%Y-%m-%d')
if start_day.weekday() < 6:
    start_day = start_day - datetime.timedelta(start_day.weekday() + 1 - 7)

time_intervals = []
from_day = start_day - datetime.timedelta(7)
day_max = datetime.datetime.now()
while from_day < day_max:
    to_day = from_day + datetime.timedelta(7)
    time_intervals.append({
        'from': from_day.date(),
        'to': to_day.date(),
        'label': to_day.date().isoformat(),
    })
    from_day += datetime.timedelta(7)
# time_intervals.reverse()

open_bugs_by_day_and_team, open_s1_bugs_by_day, open_bugs_by_day_and_os, fixed_bug_count_by_day = get_bugs(time_intervals)
write_csv(open_bugs_by_day_and_team, open_s1_bugs_by_day, open_bugs_by_day_and_os, fixed_bug_count_by_day)

