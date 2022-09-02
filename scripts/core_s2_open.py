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
]

SEVERITIES = ['S2']

STATUS_OPEN = ['UNCONFIRMED', 'NEW', 'ASSIGNED', 'REOPENED']

BUG_CREATION_START = '2020-07-01'
# BUG_CREATION_BEFORE = '2022-07-01'

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
            bug_states = get_relevant_bug_changes(bug_data, ["product", "component", "severity", "status", "resolution"], start_date, end_date)
            if bug_states["severity"]["new"] not in SEVERITIES:
                continue
            if bug_states["product"]["new"] not in PRODUCTS_TO_CHECK:
                continue
            team = get_component_to_team(bug_states["product"]["new"], bug_states["component"]["new"]) or "Unknown"
            if team not in teams:
                teams.add(team)
            if bug_states["status"]["new"] in STATUS_OPEN:
                if bug_data['id'] not in bugs_by_date[date_label]:
                    bugs_by_date[date_label][bug_data['id']] = team
            if bug_states["status"]["old"] in STATUS_OPEN and bug_states["resolution"]["new"] == "FIXED":
                if bug_data['id'] not in fixed_bugs_by_date[date_label]:
                    fixed_bugs_by_date[date_label][bug_data['id']] = team

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
              'severity',
              'creation_time',
              'history',
             ]

    params = {
        'include_fields': fields,
        'f1': 'bug_severity',
        'o1': 'equals',
        'v1': SEVERITIES,
        'f2': 'creation_ts',
        'o2': 'greaterthan',
        'v2': BUG_CREATION_START,
        # 'f3': 'creation_ts',
        # 'o3': 'lessthan',
        # 'v3': BUG_CREATION_BEFORE,
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    params = {
        'include_fields': fields,
        'f1': 'bug_severity',
        'o1': 'changedfrom',
        'v1': SEVERITIES,
        'f2': 'creation_ts',
        'o2': 'greaterthan',
        'v2': BUG_CREATION_START,
        # 'f3': 'creation_ts',
        # 'o3': 'lessthan',
        # 'v3': BUG_CREATION_BEFORE,
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
        for bug_id, team in open_bugs.items():
            open_bugs_for_day_by_team[team].append(bug_id)
        open_bugs_by_day_and_team.append({
            "date": date,
            "teams": open_bugs_for_day_by_team
        })

    fixed_bug_count_by_day = []
    bugs_by_date_list = sorted([{key: value} for key, value in fixed_bugs_by_date.items()], key = lambda item: list(item.keys())[0])
    for bugs_for_single_day_dict in bugs_by_date_list:
        key = list(bugs_for_single_day_dict.keys())[0]
        fixed_bug_count_by_day.append({key: bugs_for_single_day_dict[key]})

    return open_bugs_by_day_and_team, fixed_bug_count_by_day

def write_csv(open_bugs_by_day_and_team, fixed_bug_count_by_day):
    with open('data/core_s2_burndown.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Open Core bugs with severity S2 filed since 2020-07-01'])
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

        row = ['fixed'] + [len(list(day_data.values())[0]) for day_data in fixed_bug_count_by_day]
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


start_day = datetime.datetime.strptime(BUG_CREATION_START, '%Y-%m-%d')
if start_day.weekday() < 6:
    start_day = start_day - datetime.timedelta(start_day.weekday() + 1 - 7)

time_intervals = []
from_day = start_day - datetime.timedelta(7)
day_max = min(datetime.datetime(2023, 1, 1), datetime.datetime.now())
while from_day < day_max:
    to_day = from_day + datetime.timedelta(7)
    time_intervals.append({
        'from': from_day.date(),
        'to': to_day.date(),
        'label': to_day.date().isoformat(),
    })
    from_day += datetime.timedelta(7)
# time_intervals.reverse()

open_bugs_by_day_and_team, fixed_bug_count_by_day = get_bugs(time_intervals)
write_csv(open_bugs_by_day_and_team, fixed_bug_count_by_day)

