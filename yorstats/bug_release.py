# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import csv
from dateutil.relativedelta import relativedelta
from libmozdata.bugzilla import Bugzilla
from .logger import logger
from . import buildhub, utils


SEVERITIES = {'blocker': 'blocker+critical+major',
              'critical': 'blocker+critical+major',
              'major': 'blocker+critical+major',
              'normal': 'normal',
              'minor': 'minor+trivial',
              'trivial': 'minor+trivial'}

WFMT = '{}-{:02d}'


def get_weeks(start_date, end_date):
    res = []
    while start_date <= end_date:
        y, w, _ = start_date.isocalendar()
        res.append(WFMT.format(y, w))
        start_date += relativedelta(days=7)
    return res


def get_bugs(major):

    def bug_handler(bug, data):
        sev = bug['severity']
        del bug['severity']
        creation = utils.get_date(bug['creation_time'])
        year, week, _ = creation.isocalendar()
        t = WFMT.format(year, week)
        data[SEVERITIES[sev]][t] += 1

    # start_date is the date for the first nightly
    # final_date is the date for the first release (or today if no release)
    start_date, final_date = buildhub.get_range(major)
    weeks = get_weeks(start_date, final_date)
    data = {sev: {w: 0 for w in weeks} for sev in set(SEVERITIES.values())}
    queries = []
    fields = ['creation_time', 'severity']
    params = {
        'include_fields': fields,
        'product': ['Firefox', 'Core', 'Firefox for Android',
                    'DevTools', 'Firefox Build System',
                    'Testing', 'Toolkit', 'WebExtensions'],
        'f1': 'creation_ts',
        'o1': 'greaterthaneq',
        'v1': '',
        'f2': 'creation_ts',
        'o2': 'lessthan',
        'v2': '',
        'f3': 'cf_last_resolved',
        'o3': 'lessthan',
        'v3': final_date,
        'f4': 'bug_severity',
        'o4': 'notequals',
        'v4': 'enhancement',
        'f5': 'keywords',
        'o5': 'notsubstring',
        'v5': 'meta',
        'f6': 'resolution',
        'o6': 'isnotempty',
        'f7': 'cf_status_firefox' + str(major),
        'o7': 'anyexact',
        'v7': 'affected, fix-optional, fixed, wontfix, verified, disabled'
    }

    while start_date <= final_date:
        end_date = start_date + relativedelta(days=30)
        params = params.copy()

        # start_date <= creation_ts < end_date
        params['v1'] = start_date
        params['v2'] = end_date
        
        logger.info('Bugzilla: From {} To {}'.format(start_date, end_date))

        queries.append(Bugzilla(params,
                                bughandler=bug_handler,
                                bugdata=data,
                                timeout=960))
        start_date = end_date

    for q in queries:
        q.get_data().wait()

    first_beta = buildhub.get_first_beta(major)
    y, w, _ = first_beta.isocalendar()
    data['first_beta'] = WFMT.format(y, w)

    return data


def write_csv(major):
    data = get_bugs(major)
    with open('data/bugs_count_{}.csv'.format(major), 'w') as Out:
        writer = csv.writer(Out, delimiter=',')
        weeks = list(sorted(data['normal'].keys()))
        head = ['Severity'] + weeks
        writer.writerow(head)
        for sev in ['blocker+critical+major', 'normal', 'minor+trivial']:
            numbers = data[sev]
            numbers = [numbers[w] for w in weeks]
            writer.writerow([sev] + numbers)
        writer.writerow([])
        writer.writerow(['First beta', data['first_beta']])


write_csv(64)
