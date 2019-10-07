# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import datetime
import json
import pytz
import requests
import time
from logger import logger
import utils

# Provides the date and time a build was _started_. Publication on the server
# is done after the build is complete, shipping to the users happens at the
# same time like publication for Nightly, is one day after the build for beta
# (after QA has checked the build) and up to a week for release (if the first
# release candidate has no issues which require a new one).
BUILDHUB_URL = 'https://buildhub.moz.tools/api/search'

# Currently (2019-09), there is no public API which provides information about
# the time when a build got shipped, the product details API provides the date.
PRODUCT_DETAILS_URL = 'https://product-details.mozilla.org/1.0/firefox.json'


def make_buildhub_request(params, sleep, retry, callback):
    """Query Buildhub to get build date"""
    params = json.dumps(params)

    for _ in range(retry):
        r = requests.post(BUILDHUB_URL, data=params)
        if 'Backoff' in r.headers:
            time.sleep(sleep)
        else:
            try:
                return callback(r.json())
            except BaseException as e:
                logger.error(
                    'Buildhub query failed with parameters: {}.'.format(params)
                )
                logger.error(e, exc_info=True)
                return None

    logger.error('Too many attempts in make_buildhub_request (retry={})'.format(retry))

    return None


def make_productdetails_request(product_and_version, sleep, retry, callback):
    """Query productdetails to get release date"""

    for _ in range(retry):
        r = requests.get(PRODUCT_DETAILS_URL)
        if 'Backoff' in r.headers:
            time.sleep(sleep)
        else:
            release_date_str = None
            try:
                release_date_str = (r.json())['releases'][product_and_version]['date']
            except KeyError as e:
                # ['releases'][product_and_version]['date'] was not found.
                # Should be due to the version not being released yet.
                return utils.get_date('today'), False
            except BaseException as e:
                logger.error(
                    'productdetails query failed'
                )
                logger.error(e, exc_info=True)
                return None
            # The release time is not publicly available. Set it to 6am PDT when
            # releases are often done.
            release_date = datetime.datetime.strptime(release_date_str, '%Y-%m-%d')
            release_time = datetime.time(13)
            release_datetime = datetime.datetime.combine(release_date, release_time)
            release_datetime = pytz.utc.localize(release_datetime)
            return release_datetime, True

    logger.error('Too many attempts in make_productdetails_request(retry={})'.format(retry))

    return None


def get_date(data):
    buckets = data['aggregations']['buildids']['buckets']
    if len(buckets) >= 1:
        buildid = buckets[0]['key']
        return utils.get_build_date(buildid), True
    return utils.get_date('today'), False


def get_buildhub_query(major, channels):
    version_pat = '{}[0-9\.]+(([ab][0-9]+))?'.format(major)
    return {
        'aggs': {
            'buildids': {
                'terms': {
                    'field': 'build.id',
                    'size': 1000,
                    'order': {'_term': 'asc'},
                }
            },
        },
        'query': {
            'bool': {
                'filter': [
                    {'regexp': {'target.version': {'value': version_pat}}},
                    {'terms': {'target.channel': channels}},
                    {'terms': {'source.product': ['firefox', 'fennec', 'devedition']}},
                ]
            }
        },
        'size': 0,
    }


def get_product_dates(major):
    """Get the date of the first nightly and the first date of release"""
    data = get_buildhub_query(major, ['nightly'])
    nightly_start, nightly_started = make_buildhub_request(data, 1, 100, get_date)
    print('Nightly start: {}'.format(nightly_start))
    data = get_buildhub_query(major, ['beta'])
    beta_start, beta_started = make_buildhub_request(data, 1, 100, get_date)
    print('Beta start: {}'.format(beta_start))
    release_date, release_started = make_productdetails_request('firefox-{}.0'.format(major), 1, 100, get_date)
    print('Release date: {}'.format(release_date))
    successor_release_date, successor_started = make_productdetails_request('firefox-{}.0'.format(major + 1), 1, 100, get_date)
    print('Successor release date: {}'.format(successor_release_date))
    
    return nightly_start, beta_start, release_date, successor_release_date, nightly_started, beta_started, release_started, successor_started

