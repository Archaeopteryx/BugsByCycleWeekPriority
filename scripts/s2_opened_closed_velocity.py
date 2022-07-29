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

STATUS_VERSION_EVER_AFFECTED = [
  'affected',
  'fix-optional',
  'fixed',
  'wontfix',
  'verified',
]

STATUS_VERSION_NEVER_AFFECTED = [
  'disabled',
  'unaffected',
  'verified disabled',
]

STATUS_VERSION_STILL_AFFECTED = [
  'affected',
  'fix-optional',
  'wontfix',
]

STATUS_VERSION_FIXED = [
  'fixed',
  'verified'
]

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

def get_status_for_versions(bug_data, adjust_fixed_for_dot_release=False):
    status_for_versions = {}
    for field, value in bug_data.items():
        if not field.startswith('cf_status_firefox'):
            continue
        # Replace with str.removeprefix added in Python 3.9
        version = field.split('cf_status_firefox')[1]
        if version.startswith('_esr'):
            continue
        if "_" in version:
            # Some special dot releases got their own status flag, e.g. "67_0_1"
            continue
        status_for_versions[int(version)] = value

    unaffected_versions = [version for version, status in status_for_versions.items() if status in STATUS_VERSION_NEVER_AFFECTED]
    unaffected_highest_version = max(unaffected_versions) if len(unaffected_versions) > 0 else None

    fixed_versions = [version for version, status in status_for_versions.items() if status in STATUS_VERSION_FIXED]
    fixed_lowest_version = min(fixed_versions) if len(fixed_versions) > 0 else None
    fixed_lowest_bumped_for_fix_after_release = False
    if adjust_fixed_for_dot_release and fixed_lowest_version:
        fixed_lowest_version_latest = None
        for historyItem in bug_data['history']:
            for change in historyItem['changes']:
                change_time_str = historyItem['when']
                change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                change_time = pytz.utc.localize(change_time).date()
                if change['field_name'] == f'cf_status_firefox{fixed_lowest_version}' and change['added'] == 'fixed':
                    fixed_lowest_version_latest = change_time
        fixed_full_version = f'{fixed_lowest_version}.0'
        if fixed_lowest_version_latest and fixed_full_version in release_dates and fixed_lowest_version_latest >= release_dates[fixed_full_version]:
            fixed_lowest_bumped_for_fix_after_release = True
            print(f'bumped bug {bug_data["id"]} as fixed from version {fixed_lowest_version} to {fixed_lowest_version + 1} at {change_time} on or after release on {release_dates[fixed_full_version]}')
            fixed_lowest_version += 1

    unfixed_versions = [version for version, status in status_for_versions.items() if status in STATUS_VERSION_STILL_AFFECTED]
    if fixed_lowest_bumped_for_fix_after_release and unaffected_highest_version and fixed_lowest_version - 1 > unaffected_highest_version:
        unfixed_versions.append(fixed_lowest_version - 1)
    unfixed_lowest_version = min(unfixed_versions) if len(unfixed_versions) > 0 else None

    if unaffected_highest_version is not None and unfixed_lowest_version is not None and unaffected_highest_version > unfixed_lowest_version:
        unfixed_lowest_version = None

    return {
      "fixed_lowest_version": fixed_lowest_version,
      "unfixed_lowest_version": unfixed_lowest_version,
      "unaffected_highest_version": unaffected_highest_version,
    }

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
                if bug_data["resolution"] == "FIXED":
                    resolved_time = datetime.datetime.strptime(bug_data['cf_last_resolved'], '%Y-%m-%dT%H:%M:%SZ')
                    resolved_time = pytz.utc.localize(resolved_time).date()
                    if str(resolved_time) > '2022-06-30':
                        continue
                    bug_id = bug_data["id"]
                    if bug_id not in fixed_bugs_data:
                        fixed_bugs_data[bug_id] = {
                            "status_for_versions": get_status_for_versions(bug_data, adjust_fixed_for_dot_release=True),
                            "regressed_by": bug_data["regressed_by"],
                            "creation_time": bug_data["creation_time"]
                        }
                if bug_data['id'] not in fixed_bugs_by_date[date_label]:
                    fixed_bugs_by_date[date_label].append(bug_data['id'])
                if creation_time < start_date:
                    if bug_data['id'] not in fixed_old_bugs_by_date[date_label]:
                        fixed_old_bugs_by_date[date_label].append(bug_data['id'])

    def regressed_by_handler(bug_data):
        bug_id = bug_data["id"]
        if bug_data["resolution"] == "FIXED":
            regressed_by_bugs_data[bug_id] = {
                "status_for_versions": get_status_for_versions(bug_data, adjust_fixed_for_dot_release=False),
            }
        else:
            regressed_by_bugs_data[bug_id] = {}

    start_date = time_intervals[0]['from']

    bugs_by_date = {}
    fixed_bugs_data = {}
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
              'regressed_by',
              '_custom',
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

    # For fixed bugs whose first affected version is unknown, check the bug which
    # caused the regression (if the bug is known) for which version it landed.
    regressing_bugs = list(set([fixed_bugs_data[bug_id]["regressed_by"][0] for bug_id in fixed_bugs_data if len(fixed_bugs_data[bug_id]["regressed_by"]) > 0]))
    regressed_by_bugs_data = {}

    fields = [
              'id',
              'resolution',
              '_custom',
              'history',
             ]

    params = {
        'include_fields': fields,
    }

    for range_start in range(0, len(regressing_bugs), 500):
        bug_ids = regressing_bugs[range_start:min(range_start + 500, len(regressing_bugs))]
        params['id'] = ",".join([str(bug_id) for bug_id in bug_ids])

        Bugzilla(params,
                 bughandler=regressed_by_handler,
                 timeout=960).get_data().wait()

    for (bug_id, regressed_by) in list(set([(bug_id, fixed_bugs_data[bug_id]["regressed_by"][0]) for bug_id in fixed_bugs_data if len(fixed_bugs_data[bug_id]["regressed_by"]) > 0])):
        if regressed_by_bugs_data[regressed_by]:
            version_regression_started = regressed_by_bugs_data[regressed_by]["status_for_versions"]["fixed_lowest_version"]
            if version_regression_started:
                fixed_lowest_version = fixed_bugs_data[bug_id]["status_for_versions"]["fixed_lowest_version"]
                fixed_bugs_data[bug_id]["unfixed_lowest_version"] = version_regression_started
                if fixed_lowest_version and fixed_lowest_version <= version_regression_started:
                    fixed_bugs_data[bug_id]["status_for_versions"]["unfixed_lowest_version"] = None
                    fixed_bugs_data[bug_id]["status_for_versions"]["unaffected_highest_version"] = fixed_lowest_version - 1
                else:
                    fixed_bugs_data[bug_id]["status_for_versions"]["unfixed_lowest_version"] = version_regression_started
                    fixed_bugs_data[bug_id]["status_for_versions"]["unaffected_highest_version"] = version_regression_started - 1

    # Bugzilla doesn't contain the information which version was first affected/
    # the last unaffected.
    # Use the date the bug got reported and assume the Nightly/mozilla-central
    # version for that day is the first affected one.
    nightly_start_data = productdates.get_latest_nightly_versions_by_min_version(1)
    for bug_id in fixed_bugs_data:
        if fixed_bugs_data[bug_id]["status_for_versions"]["unaffected_highest_version"] is None:
            creation_time_str = fixed_bugs_data[bug_id]["creation_time"]
            creation_time = datetime.datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%SZ')
            creation_time = pytz.utc.localize(creation_time).date()
            first_affected_version = None
            version_start_bug_creation_diff_min = None
            for nightly_start in nightly_start_data:
                version_start_bug_creation_diff = (creation_time - nightly_start["date"]).days
                if version_start_bug_creation_diff >= 0:
                    if first_affected_version is None or version_start_bug_creation_diff < version_start_bug_creation_diff_min:
                        first_affected_version = nightly_start["version"]
                        version_start_bug_creation_diff_min = version_start_bug_creation_diff
            if first_affected_version and first_affected_version < fixed_bugs_data[bug_id]["status_for_versions"]["fixed_lowest_version"]:
                if first_affected_version > fixed_bugs_data[bug_id]["status_for_versions"]["unfixed_lowest_version"]:
                    first_affected_version = fixed_bugs_data[bug_id]["status_for_versions"]["unfixed_lowest_version"]
                fixed_bugs_data[bug_id]["status_for_versions"]["unaffected_highest_version"] = first_affected_version - 1

    affected_start_unknown = [(bug_id, fixed_bugs_data[bug_id]) for bug_id in fixed_bugs_data if fixed_bugs_data[bug_id]["status_for_versions"]["unaffected_highest_version"] is None]
    # print(f'{len(fixed_bugs_data) - len(affected_start_unknown)} of {len(fixed_bugs_data)} identified')

    bugs_by_affected_version_range = {}
    for bug_id in fixed_bugs_data:
        fixed_lowest_version = fixed_bugs_data[bug_id]["status_for_versions"]["fixed_lowest_version"]
        unaffected_highest_version = fixed_bugs_data[bug_id]["status_for_versions"]["unaffected_highest_version"]
        if not fixed_lowest_version or not unaffected_highest_version:
            continue
        versions_affected = fixed_lowest_version - unaffected_highest_version - 1
        if versions_affected not in bugs_by_affected_version_range:
            bugs_by_affected_version_range[versions_affected] = set()
        bugs_by_affected_version_range[versions_affected].add(bug_id)

    return open_bug_count_by_day, fixed_bug_count_by_day, fixed_old_bug_count_by_day, bugs_by_affected_version_range

def write_csv(open_bug_count_by_day, fixed_bug_count_by_day, fixed_old_bug_count_by_day, bugs_by_affected_version_range):
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

        writer.writerow(['Versions affected', 'Bug count', 'Bugs'])
        for versions_affected in sorted(bugs_by_affected_version_range.keys()):
            writer.writerow([
                versions_affected,
                len(bugs_by_affected_version_range[versions_affected]),
                "'" + ",".join(list(map(str, sorted(bugs_by_affected_version_range[versions_affected])))),
            ])

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

release_start_data = productdates.get_latest_released_versions_by_min_version(1)
release_dates = {}
for version_data in release_start_data:
    release_dates[version_data['version']] = version_data['date']

# Close to date when 'S<number>' severities replaced 'major', 'minor' etc.
start_date = args.start_date if args.start_date else '2022-01-02'

start_day = datetime.datetime.strptime(start_date, '%Y-%m-%d')

time_intervals = []
# First Sunday of the year
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

open_bug_count_by_day, fixed_bug_count_by_day, fixed_old_bug_count_by_day, bugs_by_affected_version_range = get_bugs(time_intervals)
write_csv(open_bug_count_by_day, fixed_bug_count_by_day, fixed_old_bug_count_by_day, bugs_by_affected_version_range)

