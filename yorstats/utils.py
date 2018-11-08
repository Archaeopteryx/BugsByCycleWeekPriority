# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from datetime import datetime
from dateutil.relativedelta import relativedelta
import dateutil.parser
import pytz
import six


def get_build_date(bid):
    if isinstance(bid, six.string_types):
        Y = int(bid[0:4])
        m = int(bid[4:6])
        d = int(bid[6:8])
        H = int(bid[8:10])
        M = int(bid[10:12])
        S = int(bid[12:])
    else:
        # 20160407164938 == 2016 04 07 16 49 38
        N = 5
        r = [0] * N
        for i in range(N):
            r[i] = bid % 100
            bid //= 100
        Y = bid
        S, M, H, d, m = r
    d = datetime(Y, m, d, H, M, S)
    dutc = pytz.utc.localize(d)

    return dutc


def get_buildid(date):
    return date.strftime('%Y%m%d%H%M%S')


def get_date(dt):
    """Get a datetime from a string 'Year-month-day'

    Args:
        dt (str): a date

    Returns:
        datetime: a datetime object
    """
    assert dt

    if isinstance(dt, datetime):
        return as_utc(dt)

    if dt == 'today':
        return pytz.utc.localize(datetime.utcnow())
    elif dt == 'tomorrow':
        return pytz.utc.localize(datetime.utcnow() + relativedelta(days=1))
    elif dt == 'yesterday':
        return pytz.utc.localize(datetime.utcnow() - relativedelta(days=1))

    return as_utc(dateutil.parser.parse(dt))


def as_utc(d):
    """Convert a date in UTC

    Args:
        d (datetime.datetime): the date

    Returns:
        datetime.datetime: the localized date
    """
    if isinstance(d, datetime):
        if d.tzinfo is None or d.tzinfo.utcoffset(d) is None:
            return pytz.utc.localize(d)
        return d.astimezone(pytz.utc)
    elif isinstance(d, date):
        return pytz.utc.localize(datetime(d.year, d.month, d.day))
