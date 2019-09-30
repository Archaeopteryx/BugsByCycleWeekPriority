# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This scripts generates a report of
# * number of bugs created by week and grouped by priority for a given
#   version number which got fixed before the release of that version.
#   It does not imply that the code regressed during that version number, only
#   that it initially got reported when it was in either Nightly (central) or
#   Beta stage. The issue can have affected also lower version numbers if it got
#   missed before or the regressing code got added to repository containing the
#   lower version number ("uplift").
# * bugs whose priority got lowered before release and increased afterwards
#   to P1.
# * bugs whose priority got increased after release to P1.
# * bugs filed before release and fixed in a dot release.
# * bugs filed before release and fixed in the successor major release as P1.
# * bugs tracked before release and fixed in a dot release.
# * bugs tracked before release and fixed in the successor major release.
# * bugs tracked before release and not fixed in this or the successor
#   major release.

import argparse
import copy
import csv
import datetime
from dateutil.relativedelta import relativedelta
import json
from libmozdata.bugzilla import Bugzilla
from logger import logger
import productdates
import pytz
import utils

PRODUCTS_TO_CHECK = [
    'Core',
    'DevTools',
    'Firefox',
    'Firefox Build System',
    'Firefox for Android',
    'Testing',
    'Toolkit',
    'WebExtensions',
]

PRIORITIES_MAP = {
              'P1': 'P1',
              'P2': 'P2',
              'P3': 'P3',
              'P4': 'P4',
              'P5': 'P5',
              '--': '--',
             }

PRIORITIES_LIST = [
                   '--',
                   'P5',
                   'P4',
                   'P3',
                   'P2',
                   'P1',
                  ]

PRIORITIES_GROUP_LIST = [
                   '--',
                   'P5',
                   'P4',
                   'P3',
                   'P2',
                   'P1',
                        ]

STATUS_FIXED = ['fixed', 'verified']
STATUS_RESOLVED = ['fixed', 'wontfix', 'verified', 'disabled']

WFMT = '{}-{:02d}'

# Bugzilla data can be loaded from file
bugzilla_data_loaded = None

# Bugzilla data can be saved froto file
bugzilla_data_to_save = {}


def add_bugzilla_data_to_save(node_path, data):
    # node_path is an array of strings representing the nodes in the JSON to
    # which the data shall be saved. The node has a child 'data' which holds the
    # data.
    node = bugzilla_data_to_save
    for path_step in node_path:
        if not path_step in node:
            node[path_step] = {'data': []}
        node = node[path_step]
    node['data'].append(data)


def get_weeks(start_date, end_date):
    res = []
    while start_date.strftime('%Y-%W') <= end_date.strftime('%Y-%W'):
        y, w, _ = start_date.isocalendar()
        res.append(WFMT.format(y, w))
        start_date += relativedelta(days=7)
    return res


def get_bugs(major):

    def bug_handler(bug_data, other_data):
#        data_opened = other_data['data_opened']
#        data_fixed = other_data['data_fixed']
#        data_resolved = other_data['data_resolved']
        phase = other_data['phase']

        if bzdata_save_path:
            add_bugzilla_data_to_save(['opened', phase], bug_data)

        pre_release_phase = True

        # Questions investigated:
        # 1. Which bugs saw their priority lowered before release (from blocker
        #    etc.)?
        # 2. Which bugs saw their priority increased after release (to blocker
        #    etc.)?
        priority_highest_index_before_release = None
        priority_index_at_release = None
        priority_highest_index_after_release = None

        # Current priority: could be changed, could be the initial value
        priority_current_index = PRIORITIES_LIST.index(bug_data['priority'])

        priority_index_last_processed = None

        # Look for changes to the 'priority' field and find the highest value
        # in the history.
        for historyItem in bug_data['history']:
            for change in historyItem['changes']:
                if change['field_name'] == 'priority':
                    change_time_str = historyItem['when']
                    change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                    change_time = pytz.utc.localize(change_time)

                    priority_old = str(change['removed'])
                    priority_new = str(change['added'])
                    priority_index_old = PRIORITIES_LIST.index(priority_old)
                    priority_index_new = PRIORITIES_LIST.index(priority_new)

                    # Ignore changes which were made after the subsequent major release
                    if change_time > successor_release_date:
                        if priority_index_last_processed is None:
                            # priority when the bug got created
                            priority_index_last_processed = priority_index_old
                        break

                    # Has the release shipped?
                    if pre_release_phase and change_time > release_date:
                        pre_release_phase = False
                        priority_index_at_release = priority_index_old
                        priority_highest_index_before_release = max(priority_highest_index_before_release, priority_index_old)
                        priority_highest_index_after_release = priority_index_new

                    # Before release
                    if pre_release_phase:
                        if priority_highest_index_before_release is None:
                            # priority when the bug got created
                            priority_highest_index_before_release = priority_index_old
                        priority_highest_index_before_release = max(priority_highest_index_before_release, priority_index_new)
                    # After release
                    else:
                        if priority_highest_index_after_release is None:
                            priority_highest_index_after_release = priority_index_new
                        else:
                            priority_highest_index_after_release = max(priority_highest_index_after_release, priority_index_new)
        if priority_index_last_processed is None:
            priority_index_last_processed = priority_current_index
        if pre_release_phase:
            # Never a change to priority, current state is start state.
            if priority_highest_index_before_release is None:
                priority_highest_index_before_release = priority_index_last_processed
            if priority_index_at_release is None:
                priority_index_at_release = priority_index_last_processed
                priority_highest_index_after_release = priority_index_last_processed
        prio_before_release = PRIORITIES_LIST[priority_highest_index_before_release]
        prio_at_release = PRIORITIES_LIST[priority_index_at_release]
        prio_after_release = PRIORITIES_LIST[priority_highest_index_after_release]
        prio_group_before_release = PRIORITIES_GROUP_LIST.index(PRIORITIES_MAP[prio_before_release])
        prio_group_at_release = PRIORITIES_GROUP_LIST.index(PRIORITIES_MAP[prio_at_release])
        prio_group_after_release = PRIORITIES_GROUP_LIST.index(PRIORITIES_MAP[prio_after_release])

        sec_bug = any('security' in group for group in bug_data['groups'])
        bug_summary = ''
        if sec_bug:
            bug_summary = '(Secure bug in %(product)s :: %(component)s)' % \
                {'product': bug_data['product'],
                 'component': bug_data['component']}
        else:
            bug_summary = bug_data['summary']

        bug_data_to_export = [
                              bug_data['id'],
                              bug_data[status_flag_version],
                              bug_data[status_flag_successor_version],
                              prio_before_release,
                              prio_at_release,
                              prio_after_release,
                              bug_data['product'],
                              bug_data['component'],
                              bug_data['assigned_to_detail']['email'],
                              bug_summary,
                            ]
        if prio_group_before_release > prio_group_at_release and prio_group_after_release > prio_group_at_release and prio_group_after_release == 5:
            prio_lowered_and_increased.append(bug_data_to_export)
        if prio_group_after_release > prio_group_at_release and prio_group_after_release == 5:
            prio_increased_after_release.append(bug_data_to_export)

        creation = utils.get_date(bug_data['creation_time'])
        year, week, _ = creation.isocalendar()
        t = WFMT.format(year, week)
        prio_group_highest = PRIORITIES_GROUP_LIST[max(prio_group_before_release, prio_group_after_release)]
        data_opened[prio_group_highest][t] += 1


        # Questions investigated:
        # 1. What was the status of the bug for this version when it got release?
        # 2. If the bug didn't get fixed before release, has it been fixed in a
        #    dot release?
        # 3. If the bug didn't get fixed before release, has it been fixed in a
        #    the major successor release?
        pre_release_phase = True

        status_flag_version_at_release = None

        # Current status: could be changed, could be the initial value
        status_flag_version_current = bug_data[status_flag_version]

        status_flag_version_last_processed = None

        last_fixed = None
        for historyItem in bug_data['history']:
            for change in historyItem['changes']:
                if change['field_name'] == status_flag_version:
                    change_time_str = historyItem['when']
                    change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                    change_time = pytz.utc.localize(change_time)

                    status_flag_version_old = str(change['removed'])
                    status_flag_version_new = str(change['added'])

                    # Ignore changes which were made after the subsequent major release
                    if change_time > successor_release_date:
                        if status_flag_version_last_processed is None:
                            # status when the bug got created
                            status_flag_version_last_processed = status_flag_version_old 
                        break

                    # Has the release shipped?
                    if pre_release_phase and change_time > release_date:
                        pre_release_phase = False
                        status_flag_version_at_release = status_flag_version_old

                    status_flag_version_last_processed = status_flag_version_new
                    if status_flag_version_new in STATUS_FIXED:
                        last_fixed = change_time
        if status_flag_version_last_processed is None:
            status_flag_version_last_processed = status_flag_version_current
        if pre_release_phase:
            if status_flag_version_at_release is None:
                status_flag_version_at_release = status_flag_version_last_processed
        fixed_before_release = status_flag_version_at_release in STATUS_FIXED
        fixed_in_dot_release = not fixed_before_release and status_flag_version_last_processed in STATUS_FIXED
        fixed_in_successor_release_priority = not fixed_before_release and not fixed_in_dot_release and bug_data[status_flag_successor_version] in STATUS_FIXED and 'P1' in [prio_before_release, prio_after_release]
        if fixed_in_dot_release:
            fixed_in_dot_release_bugs.append(bug_data_to_export)
        if fixed_in_successor_release_priority:
            fixed_in_successor_release_priority_bugs.append(bug_data_to_export)

        if last_fixed:
            fixed_date = utils.get_date(last_fixed)
            year, week, _ = fixed_date.isocalendar()
            t = WFMT.format(year, week)
            data_fixed[prio_group_highest][t] += 1

        last_resolved = None
        if phase == 'nightly':
          if not bug_data['is_open'] and bug_data['cf_last_resolved']:
              last_resolved_str = bug_data['cf_last_resolved']
              last_resolved = datetime.datetime.strptime(last_resolved_str, '%Y-%m-%dT%H:%M:%SZ')
              last_resolved = pytz.utc.localize(last_resolved)
              # Don't try to handle bug closures after the next major relase. The
              # week might not be part of the date range anymore.
              if last_resolved > successor_release_date:
                  last_resolved = None
        elif phase == 'beta':
          for historyItem in bug_data['history']:
              for change in historyItem['changes']:
                  if change['field_name'] == status_flag_version:
                      change_time_str = historyItem['when']
                      change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                      change_time = pytz.utc.localize(change_time)

                      status_flag_version_new = str(change['added'])

                      # Ignore changes which were made after the subsequent major release
                      if change_time > successor_release_date:
                          break

                      if status_flag_version_new in STATUS_RESOLVED:
                          last_resolved = change_time

        if last_resolved:
            resolved_date = utils.get_date(last_resolved)
            year, week, _ = resolved_date.isocalendar()
            t = WFMT.format(year, week)
            data_resolved[prio_group_highest][t] += 1

        # Questions investigated:
        # 1. Was set bug set as tracking for this version before it got
        #    released?
        # 2. If the tracking bug didn't get fixed before release, has it been
        #    fixed in a dot release?
        # 3. If the tracking bug didn't get fixed before release, has it been
        #    fixed in a the major successor release?
        tracking_flag_version = 'cf_tracking_firefox' + str(product_version)
        tracking_for_version = False
        for historyItem in bug_data['history']:
            for change in historyItem['changes']:
                if change['field_name'] == tracking_flag_version:
                    if change['added'] == '+':
                        tracking_for_version = True
                        break
                    change_time_str = historyItem['when']
                    change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                    change_time = pytz.utc.localize(change_time)

                    # Ignore changes which were made after the subsequent major release
                    if change_time > release_date:
                        break
        if tracking_for_version and not fixed_before_release and fixed_in_dot_release:
            tracked_fixed_in_dot_release_bugs.append(bug_data_to_export)
        if tracking_for_version and not fixed_before_release and not fixed_in_dot_release and bug_data[status_flag_successor_version] in STATUS_FIXED:
            tracked_fixed_in_successor_release_bugs.append(bug_data_to_export)
        if tracking_for_version and not fixed_before_release and not fixed_in_dot_release and not bug_data[status_flag_successor_version] in STATUS_FIXED:
            tracked_not_fixed_in_this_or_successor_release_bugs.append(bug_data_to_export)


    prio_lowered_and_increased = []
    prio_increased_after_release = []

    fixed_in_dot_release_bugs = []
    fixed_in_successor_release_priority_bugs = []

    tracked_fixed_in_dot_release_bugs = []
    tracked_fixed_in_successor_release_bugs = []
    tracked_not_fixed_in_this_or_successor_release_bugs = []

    data_opened = {prio: {w: 0 for w in weeks} for prio in set(PRIORITIES_MAP.values())}
    data_fixed = {prio: {w: 0 for w in weeks} for prio in set(PRIORITIES_MAP.values())}
    data_resolved = {prio: {w: 0 for w in weeks} for prio in set(PRIORITIES_MAP.values())}

    # Load Bugzilla data from file
    if bzdata_load_path:
        for bug_data in bugzilla_data_loaded['opened']['nightly']['data']:
            other_data = {
                          'phase' : 'nightly',
                          'data_opened' : data_opened,
                          'data_fixed' : data_fixed,
                          'data_resolved' : data_resolved,
                          'prio_lowered_and_increased' : prio_lowered_and_increased,
                          'prio_increased_after_release' : prio_increased_after_release,
                          'fixed_in_dot_release_bugs': fixed_in_dot_release_bugs,
                          'fixed_in_successor_release_priority_bugs': fixed_in_successor_release_priority_bugs,
                          'tracked_fixed_in_dot_release_bugs': tracked_fixed_in_dot_release_bugs,
                          'tracked_fixed_in_successor_release_bugs': tracked_fixed_in_successor_release_bugs,
                         }
            bug_handler(bug_data, other_data)
        for bug_data in bugzilla_data_loaded['opened']['beta']['data']:
            other_data = {
                          'phase' : 'nightly',
                          'data_opened' : data_opened,
                          'data_fixed' : data_fixed,
                          'data_resolved' : data_resolved,
                          'prio_lowered_and_increased' : prio_lowered_and_increased,
                          'prio_increased_after_release' : prio_increased_after_release,
                          'fixed_in_dot_release_bugs': fixed_in_dot_release_bugs,
                          'fixed_in_successor_release_priority_bugs': fixed_in_successor_release_priority_bugs,
                          'tracked_fixed_in_dot_release_bugs': tracked_fixed_in_dot_release_bugs,
                          'tracked_fixed_in_successor_release_bugs': tracked_fixed_in_successor_release_bugs,
                          'tracked_not_fixed_in_this_or_successor_release_bugs': tracked_not_fixed_in_this_or_successor_release_bugs,
                         }
            bug_handler(bug_data, other_data)
    # Load Bugzilla data from Bugzilla server
    else:
        queries = []
        fields = [
                  'id',
                  'summary',
                  'product',
                  'component',
                  'creation_time',
                  'priority',
                  'assigned_to',
                  'is_open',
                  'cf_last_resolved',
                  status_flag_version,
                  status_flag_successor_version,
                  'history',
                  'groups',
                 ]

        nightly_params = {
            'include_fields': fields,
            'product': PRODUCTS_TO_CHECK,
            'f1': 'creation_ts',
            'o1': 'greaterthaneq',
            'v1': '',
            'f2': 'creation_ts',
            'o2': 'lessthan',
            'v2': '',
            'f3': 'keywords',
            'o3': 'notsubstring',
            'v3': 'meta',
        }

        beta_params = {
            'include_fields': fields,
            'product': PRODUCTS_TO_CHECK,
            'f1': 'creation_ts',
            'o1': 'greaterthaneq',
            'v1': '',
            'f2': 'creation_ts',
            'o2': 'lessthan',
            'v2': '',
            'f3': 'keywords',
            'o3': 'notsubstring',
            'v3': 'meta',
            'f4': status_flag_version,
            'o4': 'anyexact',
            'v4': 'affected, fix-optional, fixed, wontfix, verified, disabled',
        }

        phases = [
            {
                'name' : 'nightly',
                'query_params' : nightly_params,
                'start_date' : nightly_start,
                'end_date' : beta_start,
            },
            {
                'name' : 'beta',
                'query_params' : beta_params,
                'start_date' : beta_start,
                'end_date' : release_date,
            },
        ]
        for phase in phases:
            query_start = phase['start_date']
            while query_start <= phase['end_date']:
                query_end = query_start + relativedelta(days=30)
                params = phase['query_params'].copy()

                # query_start <= creation_ts < query_end
                params['v1'] = query_start
                params['v2'] = min(query_end, phase['end_date'])
                
                logger.info('Bugzilla: From {} To {}'.format(query_start, query_end))

                queries.append(Bugzilla(params,
                                        bughandler=bug_handler,
                                        bugdata={
                                                 'phase' : phase['name'],
#                                                 'data_opened' : data_opened,
#                                                 'prio_lowered_and_increased' : prio_lowered_and_increased,
#                                                 'prio_increased_after_release' : prio_increased_after_release,
                                                },
                                        timeout=960))
                query_start = query_end

        for q in queries:
            q.get_data().wait()

    y, w, _ = beta_start.isocalendar()
    data_opened['first_beta'] = WFMT.format(y, w)

    return (
            data_opened,
            data_fixed,
            data_resolved,
            prio_lowered_and_increased,
            prio_increased_after_release,
            fixed_in_dot_release_bugs,
            fixed_in_successor_release_priority_bugs,
            tracked_fixed_in_dot_release_bugs,
            tracked_fixed_in_successor_release_bugs,
            tracked_not_fixed_in_this_or_successor_release_bugs,
           )

def log(message):
    print(message)


def write_csv(major):
    (
     data_opened,
     data_fixed,
     data_resolved,
     prio_lowered_and_increased,
     prio_increased_after_release,
     fixed_in_dot_release_bugs,
     fixed_in_successor_release_priority_bugs,
     tracked_fixed_in_dot_release_bugs,
     tracked_fixed_in_successor_release_bugs,
     tracked_not_fixed_in_this_or_successor_release_bugs,
    ) = get_bugs(major)
    with open('data/bugs_count_{}.csv'.format(major), 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        y, w, _ = beta_start.isocalendar()
        first_beta_str = WFMT.format(y, w)
        writer.writerow(['First beta', first_beta_str])

        writer.writerow([])
        writer.writerow([])

        head = ['priority'] + weeks

        writer.writerow(['Opened bugs by week'])
        writer.writerow(head)
        for prio in PRIORITIES_GROUP_LIST:
            opened_for_prio = data_opened[prio]
            numbers = [opened_for_prio[w] for w in weeks]
            writer.writerow([prio] + numbers)

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Fixed bugs by week'])
        writer.writerow(head)
        for prio in PRIORITIES_GROUP_LIST:
            fixed_for_prio = data_fixed[prio]
            numbers = [fixed_for_prio[w] for w in weeks]
            writer.writerow([prio] + numbers)

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Closed bugs by week (fixed, duplicates, invalid, worksforme etc.)'])
        writer.writerow(head)
        for prio in PRIORITIES_GROUP_LIST:
            resolved_for_prio = data_resolved[prio]
            numbers = [resolved_for_prio[w] for w in weeks]
            writer.writerow([prio] + numbers)

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Net opened bugs by week (- = more closed than opened)'])
        writer.writerow(head)
        data_net_opened = {prio: {w: data_opened[prio][w] - data_resolved[prio][w] for w in weeks} for prio in set(PRIORITIES_MAP.values())}
        for prio in PRIORITIES_GROUP_LIST:
            open_for_prio = data_net_opened[prio]
            numbers = [open_for_prio[w] for w in weeks]
            writer.writerow([prio] + numbers)

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Open bugs by week'])
        writer.writerow(head)
        data_open = {prio: {w: 0 for w in weeks} for prio in set(PRIORITIES_MAP.values())}
        for prio in PRIORITIES_GROUP_LIST:
            data_prio_open = [0] * len(weeks)
            open_bugs = 0
            data_open = []
            for w in weeks:
                open_bugs += data_net_opened[prio][w]
                data_open.append(open_bugs)
            writer.writerow([prio] + data_open)

        tables_to_generate = [
          { 
            'variable' : prio_lowered_and_increased,
            'title' : 'Bugs with priority significantly lowered before release and increased afterwards',
          },
          { 
            'variable' : prio_increased_after_release,
            'title' : 'Bugs with priority significantly increased after release',
          },
          { 
            'variable' : fixed_in_dot_release_bugs,
            'title' : 'Bugs filed before release and fixed in dot release',
          },
          { 
            'variable' : fixed_in_successor_release_priority_bugs,
            'title' : 'Bugs filed before release and fixed in successor release as P1',
          },
          { 
            'variable' : tracked_fixed_in_dot_release_bugs,
            'title' : 'Bugs tracked before release and fixed in dot release',
          },
          { 
            'variable' : tracked_fixed_in_successor_release_bugs,
            'title' : 'Bugs tracked before release and fixed in successor release',
          },
          { 
            'variable' : tracked_not_fixed_in_this_or_successor_release_bugs,
            'title' : 'Bugs tracked before release and not fixed in this or successor release',
          },
        ]

        for table_to_generate in tables_to_generate:
            writer.writerow([])
            writer.writerow([])

            writer.writerow([table_to_generate['title']])
            writer.writerow([
                             'Bug ID',
                             'Status Version {}'.format(major),
                             'Status Version {}'.format(major + 1),
                             'Highest Priority Before Release',
                             'Priority At Release',
                             'Highest Priority After Release',
                             'Product',
                             'Component',
                             'Assignee',
                             'Summary',
                           ])
            for row in table_to_generate['variable']:
                writer.writerow([unicode(string).encode('utf-8') for string in row])


parser = argparse.ArgumentParser(description='Count bugs created and fixed before release, by week')
parser.add_argument('product_version', type=int,
                    help='Firefox version')
parser.add_argument('--bzdata-load',
                    nargs='?',
                    default=argparse.SUPPRESS,
                    help='Load the Bugzilla data from a local JSON file. If no path is provided '
                         'the program will try to load "bugzilla_data_<versionnumber>.json" from the "data" folder.')
parser.add_argument('--bzdata-save',
                    nargs='?',
                    default=argparse.SUPPRESS,
                    help='Save the Bugzilla data to a local JSON file. If no path is provided '
                         'the program will try to save as "bugzilla_data_<versionnumber>.json" into the "data" folder.')
args = parser.parse_args()

# Firefox version for which the report gets generated.
product_version = args.product_version

# Bugzilla status flag for this version
status_flag_version = 'cf_status_firefox' + str(product_version)
status_flag_successor_version = 'cf_status_firefox' + str(product_version + 1)

# nightly_start is the date for the first nightly
# beta_start is the datetime the first beta build started (or now if no beta yet)
nightly_start, beta_start, release_date, successor_release_date = productdates.get_product_dates(product_version)

weeks = get_weeks(nightly_start, successor_release_date)

bzdata_load_path = None
if 'bzdata_load' in args:
    # Load Bugzilla data from file
    if args.bzdata_load:
        # File path provided as command line argument
        bzdata_load_path = args.bzdata_load
    else:
        # No file path provided, use default location
        bzdata_load_path = 'data/bugzilla_data_{}.json'.format(product_version)
    with open(bzdata_load_path, 'r') as bugzilla_data_reader:
        bugzilla_data_loaded = json.load(bugzilla_data_reader)
    log('Loaded Bugzilla data from {}'.format(bzdata_load_path))

bzdata_save_path = None
if 'bzdata_save' in args:
    # File path to which Bugzilla data shall be saved
    if args.bzdata_save:
        # File path provided as command line argument
        bzdata_save_path = args.bzdata_save
    else:
        # No file path provided, use default location
        bzdata_save_path = 'data/bugzilla_data_{}.json'.format(product_version)

write_csv(product_version)

if bzdata_save_path:
    # Save Bugzilla data to file
    with open('data/bugzilla_data_{}.json'.format(product_version), 'w') as bugzilla_data_writer:
        bugzilla_data_writer.write(json.dumps(bugzilla_data_to_save))
        log('Saved Bugzilla data to {}'.format(bzdata_save_path))

