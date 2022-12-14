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

from utils.bugzilla import get_component_to_team

import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

needinfo_types = [
    {
        'key': 'assignee_no_login',
        'label': 'Assignee has not logged into Bugzilla for 7 months',
        'search_term': 'The bug assignee didn\'t login in'
    },
    {
        'key': 'leave_open_no_activity',
        'label': 'leave-open keyword set but no recent activity',
        'search_term': 'The leave-open keyword is there and there is no activity',
        'reaction_conditions': {
            'fields': ['keywords', 'status']
        }
    },
    {
        'key': 'needinfo_regression_author',
        'label': 'User is developer of regressor',
        'search_term': 'since you are the author of the regressor'
    },
    {
        'key': 'regressed_by_bug_missing',
        'label': '\'Regression\' keyword set but \'Regressed By\' empty',
        'search_term': 'could you fill (if possible) the regressed_by field',
        'reaction_conditions': {
            'fields': ['regressed_by']
        }
    },
    {
        'key': 'low_severity_but_tracked',
        'label': 'Low severity but tracked for version(s)',
        'search_term': 'the bug is marked as tracked for',
        'reaction_conditions': {
            'fields': ['severity']
        }
    },
    {
        'key': 'low_severity_high_performance_impact',
        'label': 'Low severity but high performance impact',
        'search_term': 'increasing the severity of this performance-impacting bug',
        'reaction_conditions': {
            'fields': ['severity']
        }
    },
    {
        'key': 'low_severity_many_votes_and_cc',
        'label': 'Low severity but many votes and CCs',
        'search_term': 'The severity field for this bug is relatively low',
        'reaction_conditions': {
            'fields': ['severity']
        }
    },
    {
        'key': 'low_severity_high_security_rating',
        'label': 'Low severity but high security rating',
        'search_term': 'However, the bug is flagged with the',
        'reaction_conditions': {
            'fields': ['severity']
        }
    },
    {
        'key': 'low_severity_high_accessibility_severity',
        'label': 'Low severity but high accessibility severity',
        'search_term': 'the accessibility severity is higher',
        'reaction_conditions': {
            'fields': ['severity']
        }
    },
    {
        'key': 'severity_missing',
        'label': 'Severity missing',
        'search_term': 'The severity field is not set for this bug.',
        'reaction_conditions': {
            'fields': ['severity']
        }
    },
    {
        'key': 'patch_reviewed_but_not_landed',
        'label': 'Patch reviewed but not landed',
        'search_term': 'which didn\'t land and no activity in this bug for'
    },
    {
        'key': 'uplift_necessary',
        'label': 'Uplift necessary? - patch landed but not for all affected branches',
        'search_term': 'is this bug important enough to require an uplift?'
    },
    {
        'key': 'meta_bug_without_dependencies',
        'label': 'The meta keyword is there, the bug doesn\'t depend on other bugs and there is no activity',
        'search_term': 'The meta keyword is there, the bug doesn\'t depend on other bugs and there is no activity'
    },
]

BUGZILLA_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

PRODUCTS_TO_CHECK = [
    'Core',
    'DevTools',
    'Firefox',
    'Firefox Build System',
    'Testing',
    'Toolkit',
    'WebExtensions',
]

# Time after which a needinfo request got cleared which gets checked if a user
# reaction got triggered, e.g. a field value like 'severity' got changed.
# In seconds
FOLLOWUP_LIMIT =  60 * 60

NEEDINFO_CREATOR_BUGZILLA_EMAIL = 'release-mgmt-account-bot@mozilla.tld'

# Maximum time difference between needinfo getting set and Bugzilla comment. Used
# to identify what the needinfo request got set for. Value in seconds.
TIME_DIFF_MAX_NEEDINFO_COMMENT = 5

def check_reaction(bug_data, initial_modification, reaction_conditions, followup_limit=FOLLOWUP_LIMIT):
    reaction_fields = reaction_conditions['fields']
    for historyItem in bug_data['history']:
        change_time = parse_time(historyItem['when'], BUGZILLA_DATETIME_FORMAT)
        if change_time > initial_modification + datetime.timedelta(seconds = followup_limit):
            return False
        for change in historyItem['changes']:
            field = change['field_name']
            if field not in reaction_fields:
                continue
            # change_time < initial_modification + followup_limit handled above
            if change_time > initial_modification - datetime.timedelta(seconds = TIME_DIFF_MAX_NEEDINFO_COMMENT):
                return True
    return False

def get_needinfo_histories(bug_data, start_date, end_date, needinfo_comment_identifier, needinfo_creator, reaction_conditions):
    needinfo_histories = {}
    for historyItem in bug_data['history']:
        for change in historyItem['changes']:
            field = change['field_name']
            if field != 'flagtypes.name':
                continue
            if not change['added'].startswith('needinfo?') and not change['removed'].startswith('needinfo?'):
                continue
            if change['removed'].startswith('needinfo?'):
                match = re.search('(?<=needinfo\?\()[^)]*(?=\))', change['removed'])
                if match:
                    user_needinfoed = match.group(0)
                    needinfo_end = parse_time(historyItem['when'], BUGZILLA_DATETIME_FORMAT)
                    if user_needinfoed in needinfo_histories.keys():
                        # Creation of needinfo flag not missing and by desired user.
                        # Even when a bug gets created and the needinfo flag used
                        # during the creation, it will be recorded as change after
                        # the bug got created.
                        if needinfo_histories[user_needinfoed][-1]['end'] is None:
                            # Creation of needinfo by desired user.
                            needinfo_histories[user_needinfoed][-1]['end'] = needinfo_end
                            reaction = check_reaction(bug_data, needinfo_end, reaction_conditions) if reaction_conditions else None
                            needinfo_histories[user_needinfoed][-1]['reaction'] = reaction
            if change['added'].startswith('needinfo?'):
                if needinfo_creator is not None and historyItem['who'] != needinfo_creator:
                    continue
                match = re.search('(?<=needinfo\?\()[^)]*(?=\))', change['added'])
                if not match:
                    continue
                user_needinfoed = match.group(0)
                needinfo_start = parse_time(historyItem['when'], BUGZILLA_DATETIME_FORMAT)
                if needinfo_comment_identifier is None:
                    if user_needinfoed not in needinfo_histories.keys():
                        needinfo_histories[user_needinfoed] = []
                    if len(needinfo_histories[user_needinfoed]) == 0 or needinfo_histories[user_needinfoed][-1]['end']:
                        needinfo_histories[user_needinfoed].append({
                            'start': needinfo_start,
                            'end': None,
                            'reaction': None,
                        })
                else:
                    for comment in bug_data['comments']:
                        if needinfo_creator is not None and comment['creator'] != needinfo_creator:
                            continue
                        if needinfo_comment_identifier not in comment['text']:
                            continue
                        comment_time = parse_time(comment['creation_time'], BUGZILLA_DATETIME_FORMAT)
                        if abs((needinfo_start - comment_time).total_seconds()) > TIME_DIFF_MAX_NEEDINFO_COMMENT:
                            continue
                        if user_needinfoed not in needinfo_histories.keys():
                            needinfo_histories[user_needinfoed] = []
                        # Under rare circumstances, it's possible the same person
                        # gets needinfo twice (e.g. with the API)
                        if len(needinfo_histories[user_needinfoed]) == 0 or needinfo_histories[user_needinfoed][-1]['end']:
                            needinfo_histories[user_needinfoed].append({
                                'start': needinfo_start,
                                'end': None,
                                'reaction': None,
                            })
                        break
    for user_needinfoed in needinfo_histories.keys():
        for i in range(len(needinfo_histories[user_needinfoed]) - 1, -1, -1):
            needinfo_start_date = needinfo_histories[user_needinfoed][i]['start'].date()
            if not (start_date <= needinfo_start_date < end_date):
                needinfo_histories[user_needinfoed].pop(i)
    return needinfo_histories

def get_needinfo_data(label, start_date, end_date, needinfo_comment_identifier, needinfo_creator=NEEDINFO_CREATOR_BUGZILLA_EMAIL, reaction_conditions={}):

    def bug_handler(bug_data):
        needinfo_histories = get_needinfo_histories(bug_data, start_date, end_date, needinfo_comment_identifier, needinfo_creator, reaction_conditions)
        for user_needinfoed in needinfo_histories.keys():
            for needinfo_history in needinfo_histories[user_needinfoed]:
                if get_component_to_team(bug_data['product'], bug_data['component']) is None:
                    print(f"team value None for bug {bug_data['id']}: {bug_data['product']} :: {bug_data['component']}")
                bugs_data.append({
                  'id': bug_data['id'],
                  'team': get_component_to_team(bug_data['product'], bug_data['component']),
                  'user_needinfoed': user_needinfoed,
                  'needinfo_history': needinfo_history,
                })

    fields = [
              'id',
              'product',
              'component',
              'comments',
              'history',
             ]

    params = {
        'include_fields': fields,
        'product': PRODUCTS_TO_CHECK,
    }

    if needinfo_comment_identifier is not None:
        params['j_top'] = 'AND_G',
        params['o1'] = 'changedby',
        params['f1'] = 'longdesc',
        params['v1'] = needinfo_creator,
        params['o2'] = 'changedafter',
        params['f2'] = 'longdesc',
        params['v2'] = start_date
        params['o3'] = 'changedbefore',
        params['f3'] = 'longdesc',
        params['v3'] = end_date
        params['o4'] = 'substring',
        params['f4'] = 'longdesc',
        params['v4'] = needinfo_comment_identifier,

    elif needinfo_creator is None:
        params['o2'] = 'changedafter',
        params['f2'] = 'flagtypes.name',
        params['v2'] = start_date
        params['o3'] = 'changedbefore',
        params['f3'] = 'flagtypes.name',
        params['v3'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    return bugs_data

def measure_data_for_interval(time_interval, needinfo_types_requested):

    start_date = time_interval['from']
    end_date = time_interval['to']
    label = time_interval['label']
    data = {}
    needinfo_types_to_process = needinfo_types_requested if needinfo_types_requested else needinfo_types
    for needinfo_type in needinfo_types_to_process:
        reaction_conditions = needinfo_type['reaction_conditions'] if 'reaction_conditions' in needinfo_type else None
        data[needinfo_type['key']] = get_needinfo_data(label, start_date, end_date, needinfo_type['key'], reaction_conditions=reaction_conditions)
    if needinfo_types_requested and 'everybodys_needinfos' in needinfo_types_requested:
        data['everybodys_needinfos'] = get_needinfo_data(label, start_date, end_date, None, needinfo_creator=None)
    elif not needinfo_types_requested:
        data['everybodys_needinfos'] = get_needinfo_data(label, start_date, end_date, None, needinfo_creator=None)

    return data

def log(message):
    print(message)

def parse_time(string, format_string):
    change_time = datetime.datetime.strptime(string, format_string)
    return pytz.utc.localize(change_time)

def measure_data(time_intervals, needinfo_types_requested):
    data_by_time_intervals = []
    for time_interval in time_intervals:
        data_by_time_intervals.append({
            'label': time_interval['label'],
            'data': measure_data_for_interval(time_interval, needinfo_types_requested)
        })

    if run_teams:
        now = datetime.datetime.utcnow()
        to_sunday = now.date() - datetime.timedelta(now.weekday() + 1)
        # Look at last 17 weeks for responsiveness by team
        from_sunday = to_sunday - datetime.timedelta(17 * 7)
        bugs_data = get_needinfo_data(to_sunday.isoformat(), from_sunday, to_sunday, None, needinfo_creator=None)

        teams_bugs = {}
        for bug_data in bugs_data:
            team = bug_data['team']
            if team not in teams_bugs:
                teams_bugs[team] = []
            teams_bugs[team].append(bug_data)
    else:
        teams_bugs = None

    return data_by_time_intervals, teams_bugs

def write_csv(data_by_time_intervals, teams_bugs, needinfo_types_requested):
    with open('data/needinfo_requests.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Needinfo requests by auto nag bot'])

        if needinfo_types_requested and 'everybodys_needinfos' in needinfo_types_requested:
            needinfo_types.append({
                'key': 'everybodys_needinfos',
                'label': 'Needinfo requests by everybody'
            })
        elif not needinfo_types_requested:
            needinfo_types_requested = needinfo_types
            needinfo_types.append({
                'key': 'everybodys_needinfos',
                'label': 'Needinfo requests by everybody'
            })

        for needinfo_type in needinfo_types:
            needinfo_key = needinfo_type['key']

            writer.writerow([])
            writer.writerow([needinfo_type['label']])

            writer.writerow([
                '',
            ]
            +
            list(reversed([data_by_time_interval['label'] for data_by_time_interval in data_by_time_intervals]))
            )

            row = ['Needinfo requests set']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                row.append(len(data[needinfo_key]))
            writer.writerow(row)
            requests_total = row[1:]

            row = ['Answered 0..1 week']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                bugs_data = []
                for bug_data in data[needinfo_key]:
                    if bug_data['needinfo_history']['end'] is not None:
                        if (bug_data['needinfo_history']['end'] - bug_data['needinfo_history']['start']) / datetime.timedelta(weeks = 1) <= 1:
                            bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

            row = ['Answered 1..2 weeks']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                bugs_data = []
                for bug_data in data[needinfo_key]:
                    if bug_data['needinfo_history']['end'] is not None:
                        if 1 < (bug_data['needinfo_history']['end'] - bug_data['needinfo_history']['start']) / datetime.timedelta(weeks = 1) <= 2:
                            bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

            row = ['Answered >2 weeks']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                bugs_data = []
                for bug_data in data[needinfo_key]:
                    if bug_data['needinfo_history']['end'] is not None:
                        if 2 < (bug_data['needinfo_history']['end'] - bug_data['needinfo_history']['start']) / datetime.timedelta(weeks = 1):
                            bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

            row = ['Unanswered']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                bugs_data = []
                for bug_data in data[needinfo_key]:
                    if bug_data['needinfo_history']['end'] is None:
                        bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)
            answered_total = []
            for pos in range(len(data_by_time_intervals)):
                answered_total.append(requests_total[pos] - row[pos + 1])

            if 'reaction_conditions' in needinfo_type:
                row = ['Action by users']
                for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                    data_by_time_interval = data_by_time_intervals[pos]
                    data = data_by_time_interval['data']
                    bugs_data = []
                    for bug_data in data[needinfo_key]:
                        if bug_data['needinfo_history']['end'] is not None:
                            if bug_data['needinfo_history']['reaction']:
                                bugs_data.append(bug_data)
                    row.append(len(bugs_data))
                writer.writerow(row)
                action_share_row = ['Action by users [share]']
                for pos in range(len(data_by_time_intervals)):
                    if answered_total[pos] == 0:
                        action_share_row.append(None)
                    else:
                        action_share_row.append('%.2f' % round(row[pos + 1] / answered_total[pos], 2))
                writer.writerow(action_share_row)


        if run_teams:
            writer.writerow([])
            writer.writerow(['Needinfo requests by everybody, grouped by components belonging to a team (last 17 weeks)'])

            teams = sorted(list(teams_bugs.keys()))
            writer.writerow([
                '',
            ]
            +
            teams
            )

            row = ['Needinfo requests set']
            for team in teams:
                row.append(len(teams_bugs[team]))
            writer.writerow(row)

            row = ['Answered 0..1 week']
            for team in teams:
                bugs_data = []
                for bug_data in teams_bugs[team]:
                    if bug_data['needinfo_history']['end'] is not None:
                        if (bug_data['needinfo_history']['end'] - bug_data['needinfo_history']['start']) / datetime.timedelta(weeks = 1) <= 1:
                            bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

            row = ['Answered 1..2 weeks']
            for team in teams:
                bugs_data = []
                for bug_data in teams_bugs[team]:
                    if bug_data['needinfo_history']['end'] is not None:
                        if 1 < (bug_data['needinfo_history']['end'] - bug_data['needinfo_history']['start']) / datetime.timedelta(weeks = 1) <= 2:
                            bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

            row = ['Answered >2 weeks']
            for team in teams:
                bugs_data = []
                for bug_data in teams_bugs[team]:
                    if bug_data['needinfo_history']['end'] is not None:
                        if 2 < (bug_data['needinfo_history']['end'] - bug_data['needinfo_history']['start']) / datetime.timedelta(weeks = 1):
                            bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

            row = ['Unanswered']
            for team in teams:
                bugs_data = []
                for bug_data in teams_bugs[team]:
                    if bug_data['needinfo_history']['end'] is None:
                        bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

available_needinfo_types = [needinfo_type['key'] for needinfo_type in needinfo_types] + ['everybodys_needinfos']

parser = argparse.ArgumentParser(description='Count open, opened and closed Firefox bugs with severity S1 or S2 by developmen cycle or week')
parser.add_argument('--version-min', type=int,
                    help='Minimum Firefox version to check')
parser.add_argument('--weeks', type=int,
                    help='Number of recent weeks to check')
parser.add_argument('--types',
                    action='store',
                    choices=available_needinfo_types,
                    nargs="+",
                    help='Only report on provided needinfo types')
parser.add_argument('--skip-teams',
                    action='store_true',
                    help='Do not generate a report about needinfo requests by team')
parser.add_argument('--debug',
                    action='store_true',
                    help='Show debug information')
args = parser.parse_args()
debug = args.debug
run_teams = not args.skip_teams
needinfo_types_requested = args.types

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
data_by_time_intervals, teams_bugs = measure_data(time_intervals, needinfo_types_requested)
write_csv(data_by_time_intervals, teams_bugs, needinfo_types_requested)

