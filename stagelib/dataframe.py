import re
from collections import defaultdict
from functools import wraps
import pandas as pd
import numpy as np
from tabulate import tabulate

import generic
from generic import mergedicts, strip, to_single_space, remove_non_ascii, fuzzyprep, integer, floating_point, punctuation
from timeutils import Date, is_dayfirst
from fieldlearner import dedupefields

pd.set_option('display.max_colwidth', -1)
#pd.options.mode.chained_assignment = None

def testdf():
    return pd.DataFrame({
        'vals':[1,2,3,4,5, '$5.00'],
        '10':["HELLO my Name is ____",2,3,4,5, '$15.00'],
        'col1':['a','               ','c','','','|||||||||||||'],
        'col1.1':['','','','d','d',''],
        'col1.2':['^^^^^^^^','b','','','','d'],
        'col2.1':['1','1.0',2,1.0,'1,000,000,000.00','1.00'],
        'col2.2':['hey','hey','hi','hi','hey','hi'],
        'name':['***john doe','hello','---','------------------','messy \t\t\t\t??','messy \t\t\t\t$$'],
        'date':['12-01-2004','April 15, 2015','aug, 27 2017','9/15/15','???????????','?'],
        'date.1':['01-12-2004','April 15, 2015','aug, 27 2017','12/10/15','16/9/15','10/12/15']})

def numeric_df():
    return pd.DataFrame({
        'a' : [3235,235,345,346,342,2153,235,3425],
        'b' : [1,34,3466,34634,643,6,346,235],
        'c': [1,2,3,4,56,5467,2354,235],
        'd' : ['B', 'D', 'D', 'D', 'B', 'A', 'A', 'B']
            })

PUNCTUPLE = tuple(punctuation)
UNWANTED = ['$', '\\', '=', '"', "'", ' ', '\t', '?', '*', '|', ' ']
NULLS = ['null', 'NULL', 'None', 'none', '<none>', '<None>', 'N/A', 'NaN', 'n/a', 'nan']
re_WHITESPACEONLY = re.compile(r'^(?:[\s]+)?$')
re_NONPRINT = re.compile(r'[^\s20-\x7E\t\r\n ]')

def dtypeobject(func):
    """Ensure series dtype is 'O' (object) or not entirely null before function execution."""
    @wraps(func)
    def inner(self, *args, **kwds):
        if self.dtype != 'O' or self.isnull().all():
            return self
        return func(self, *args, **kwds)
    return inner

def quickmapper(func):
    @wraps(func)
    def inner(self, *args, **kwds):
        return self.quickmap(lambda x: func(x, *args, **kwds))
    return inner

def assertnumeric(func):
    @wraps(func)
    def inner(self, *args, **kwds):
        if self.dtype == 'O':
            self = self.to_numeric(
                force = kwds.pop('force', True),
                integer = kwds.pop('integer', False))
        return func(self, *args, **kwds)
    return inner

def series_functions():
    global dtypeobject, quickmapper, assertnumeric, UNWANTED, re_WHITESPACEONLY

    def quickdict(self, arg, *args, **kwds):
        """Create a dictionary containing the result of a function
        or dictionary mapped against the unique values in a series.

        If arg is a dictionary/other dict-like container, non matches
        will be left as is to ensure data fidelity.

        Parameters:
        ----------

        self : SubclassedSeries
        arg : callable or dict to parse series values. (dict, idict, function)
        [kwds] : keyword arguments for arg if arg is a function or callable.
        """
        return {s : ( arg(s, *args, **kwds) if callable(arg)
            else arg.get(s, s) ) for s in self.unique()}

    def quickmap(self, arg, *args, **kwds):
        return self.map(self.quickdict(arg, *args, **kwds))

    #validators
    def contains(self, pattern, **kwds):
        """Check self (astype(str)) for a given pattern.
        Parameters:
        ----------

        self : pd.Series.
        pattern : String or compiled regex. (str, _sre.SRE_Pattern)
        [kwds] : Keyword arguments to be passed to self.str.contains.
        """
        return self\
            .astype(str)\
            .str.contains(pattern,
                na = False, **kwds)

    @assertnumeric
    def gtzero(self):
        return self > 0

    @assertnumeric
    def ltzero(self):
        return self < 0

    #modifiers
    _int = quickmapper(integer)
    _float = quickmapper(floating_point)
    _strip = quickmapper(strip)
    to_text = quickmapper(to_single_space)
    to_ascii = quickmapper(remove_non_ascii)
    to_fuzzy = quickmapper(generic.fuzzyprep)

    @dtypeobject
    def is_punctuation(self):
        return self.str.startswith(PUNCTUPLE, na = False) &\
               self.str.endswith(PUNCTUPLE, na = False)

    @dtypeobject
    def clean(self, nulls = [], *args):
        """Strip whitespace and given punctuation from self.
        In addition, attempt to locate values that consist of punctuation
        ONLY and replace with np.nan.

        Parameters:
        ----------
        self : pd.Series.
        [args] : Additional strings to strip. str
        """
        self = self.to_ascii()
        nulls.extend(nulls)
        args = tuple(UNWANTED + list(args))
        mask = (self.str.endswith(args, na = False))|\
               (self.str.startswith(args, na = False))

        self = self.modify(mask, self._strip(*args))
        return self.modify(
            (self.contains(re_WHITESPACEONLY)) |
            (self.is_punctuation()) |
            (self.isin(NULLS)),
                np.nan)

    def to_numeric(self, integer =  False, force = False, **kwds):
        """Convert values in self to a numeric data type.

        Parameters:
        ----------
        self : SubclassedSeries.
        [integer] : Flag specifying to convert as type int. bool
        """
        if integer:
            return self.fillna('').astype(str)\
                       ._int(force = force, **kwds).clean()
        return self._float(force = force, **kwds)

    def unique(self):
        return super(pd.Series, self.loc[self.notnull()]).unique()

    def to_datetime(self, fmt = False, disect = False, force = False, *args, **kwds):
        return self.quickmap(Date.parse,
                      fmt = fmt,
                      force = force,
                      disect = disect,
                      dayfirst = self.quickmap(is_dayfirst).any(),
                      *args, **kwds)

    def disectdate(self, fields = [], **kwds):
        return pd.DataFrame(
            self.to_datetime(disect = True, fields = fields, **kwds).tolist()
                )

    def modify(self, mask, ifvalue, elsevalue = None):
        """
        Modify values in a series using np.where.
        Values that meet the condition (mask) will be
        replaced with ifvalue.  All non-matching criteria
        will be replaced with elsevalue.

        Parameters
        ----------
        self : pd.Series
        mask : Boolean array. pd.Series
        ifvalue : Value used to modify current value. pd.Series, scalars

        [elsevalue] : self if used for non-matching criteria if not specified ("as is"). pd.Series
        """
        if elsevalue is None:
            elsevalue = self

        return pd.Series(
            np.where(mask, ifvalue, elsevalue),
                index = mask.index)

    for k,v in locals().items():
        setattr(pd.Series, k, v)

def dataframe_functions():

    def fieldcounts(self, fields):
        return self.filter(items = fields)\
            .stack()\
            .groupby(level = 1)\
            .count()

    def fieldcounts_unique(self, fields):
        return self.filter(items = fields).apply(pd.Series.nunique)

    def rows_containing(self, pattern, fields = [], **kwds):
        if not fields:
            fields = self.columns

        return np.column_stack([
            self[field].contains(pattern, **kwds) for field in fields
                ]).any(axis = 1)

    def joinfields(self, fields, char = ' ', **kwds):
        filtered = self.filter(items = fields)
        if filtered.empty:
            return None

        joined = filtered\
            .fillna('').astype(str)\
            .apply(lambda x: char.join(x), axis = 1)\
            .clean()

        return pd.Series([
            np.nan if not i else i for i in joined.values
                ], index = self.index).to_text()

    def dupcols(self):
        _ = pd.Index([
            re.sub(r'\.[\d]+(?:[\.\d]+)?$', '',
                   str(field)) for field in self.columns
                    ])
        __ = self.groupby(_, axis = 1).size()
        return __[__ > 1].index

    def combine_dupcols(self, field):
        """
        Fill gaps (populate nul values) in self[field] with all over-lapping columns.
        """
        try:
            series = self[field]
        except KeyError:
            series = pd.Series(None, index = self.index)

        if any(series.isnull()):
            for name in (col for col in self.columns if (field in str(col) and col != field)):
                series = series.combine_first(self[name])
        return series

    def patchmissing(self, exclude = []):
        fields = [field for field in self.dupcols()
                  if field not in exclude]
        for field in fields:
            self[field] = self.combine_dupcols(field)
        return self

    def filterfields(self, **kwds):
        return self.filter(**kwds).columns

    def drop_blankfields(self):
        return self.dropna(how = 'all', axis = 1)

    def cleanfields(self):
        """Lower case and strip whitespace in column names.

        Parameters:
        ----------
        self : pd.DataFrame.
        """
        self.columns = pd.Index(
            map(strip, self.columns.str.lower())
                    )
        return self

    def clean(self, *args, **kwds): ##ONLY for use on entire dataframe
        self.columns = dedupefields(self.columns.tolist())
        return self.apply(pd.Series.clean,
                          args = args, **kwds).drop_blankfields()
            
    def lackingdata(df, thresh = None):
        idx = df.dropna(how = 'all',
                        thresh = thresh).index
        return ~(df.index.isin(idx))

    def getmapper(self, keyfield, valuefield, where = None):

        """Create a dictionary with the values from 'keyfield'
        as dict keyfield / values from 'valuefield' as values.

        Parameters:
        -----------
        self : pd.DataFrame
        keyfield : Field name to use for dict keyfield.
        valuefield : Field name to use for dict values.
        """
        try:
            mask = self[valuefield].notnull()
            if where is not None:
                mask = mask & where

            if mask.any():
                __ = self.loc[mask].set_index(keyfield)
                return __[valuefield].to_dict()
        except KeyError:
            pass
        return {}

    def prettify(self, headers = 'keys', **kwds):
        """
        Pretty print tabular data with tabulate.

        Parameters:
        ----------
        table : Python data structure; list, dict, pd.DataFrame, etc.

        headers : str
        kwds : tabluate keyword args.
        See https://pypi.python.org/pypi/tabulate for details.
        """
        if not kwds:
            kwds.update(tablefmt = 'fancy_grid')
        return tabulate(self, headers = headers, **kwds)

    def easyagg(self, fields, flatten = True, sentinel = 'N/A', **kwds):
        """
        self.easyagg('price', {'median_price':'mean'})

        Parameters:
        ----------
        self : pd.DataFrame
        fields : str, list
            String or list of fields to groupby
        flatten : bool
            Return re-indexed.
        kwds : dict, keyword arguments
            Field name to function key, value pairs (strings).
            If no kwds are provided, the default aggregation is value counts/columns/group.
        """
        if not isinstance(fields, list):
            fields = [fields]

        funcs = kwds
        if not funcs:
            funcs = pd.Series.count

        result = self.groupby(fields).agg(funcs)
        if flatten:
            result.reset_index(inplace = True)
            result.columns = [('_'.join(field).strip('_') if len(fields) == 2 else field[0])
                              if isinstance(field, tuple) else
                              field for field in result.columns]

        return pd.DataFrame(  result.fillna(sentinel)  )

    def to_csvstring(self, quoting = 2, index = False, **kwds):
        while True:
            try:
                return self.to_csv(index = index, quoting = quoting, **kwds)
            except UnicodeEncodeError as e:
                kwds.update(encoding = 'utf-8')

    for k,v in locals().items():
        setattr(pd.DataFrame, k, v)

series_functions()
dataframe_functions()
