import builtins
import datetime
import math
import pandas
from functools import wraps
from pandas.core import series
from pandas.core.dtypes.common import is_categorical_dtype, is_float_dtype, is_string_dtype
from pandas.core.groupby.generic import SeriesGroupBy
from pandas.core.series import Series
from pandas.api.types import is_numeric_dtype

from pipda.context import ContextBase, ContextEval, ContextSelect
from pipda.symbolic import DirectRefAttr, DirectRefItem
from pipda import evaluate_expr
from pipda.utils import evaluate_args, evaluate_kwargs
from plyrda.verbs import select
import numpy
from plyrda.group_by import get_groups, get_rowwise
import re
from typing import Any, Callable, Iterable, Iterator, List, Mapping, Optional, Type, Union

from pandas import DataFrame
from pandas.core.groupby import DataFrameGroupBy
from pipda import register_func, Context

from .utils import objectize, filter_columns, select_columns
from .middlewares import Across, CAcross, Collection, DescSeries, RowwiseDataFrame, IfAny, IfAll
from .exceptions import ColumnNotExistingError

DateType = Union[int, str, datetime.date]

def _register_grouped_coln(
        func: Callable,
        context: ContextBase
) -> Callable:

    @register_func(DataFrame, context=None)
    @wraps(func)
    def wrapper(_data: DataFrame, *columns: Any, **kwargs: Any) -> Any:
        columns = [evaluate_expr(col, _data, context) for col in columns]
        if isinstance(_data, RowwiseDataFrame):
            return  func(*(row for row in zip(*columns)), **kwargs)
        # flatten
        return func(*sum((list(col) for col in columns), []), **kwargs)

    return wrapper

def _register_grouped_col1(
        func: Callable,
        context: ContextBase
) -> Callable:
    """Register a function with argument of single column as groupby aware"""

    @register_func(DataFrame, context=None)
    @wraps(func)
    def wrapper(
            _data: DataFrame,
            _column: Any,
            *args: Any,
            **kwargs: Any
    ) -> Any:
        series = evaluate_expr(_column, _data, context)
        args = evaluate_args(args, _data, context.args)
        kwargs = evaluate_kwargs(kwargs, _data, context.kwargs)
        return func(series, *args, **kwargs)

    @wrapper.register(DataFrameGroupBy)
    def _(
            _data: DataFrameGroupBy,
            _column: Any,
            *args: Any,
            **kwargs: Any
    ) -> Any:
        series = evaluate_expr(_column, _data, context)
        args = evaluate_args(args, _data, context.args)
        kwargs = evaluate_kwargs(kwargs, _data, context.kwargs)
        return series.apply(func, *args, **kwargs)

    return wrapper

def _register_grouped_col0(
        func: Callable,
        context: ContextBase
) -> Callable:
    """Register a function with argument of no column as groupby aware"""

    @register_func(DataFrame, context=None)
    @wraps(func)
    def wrapper(
            _data: DataFrame,
            *args: Any,
            **kwargs: Any
    ) -> Any:
        _column = DirectRefAttr(_data, _data.columns[0])
        series = evaluate_expr(_column, _data, context)
        args = evaluate_args(args, _data, context.args)
        kwargs = evaluate_kwargs(kwargs, _data, context.kwargs)
        return func(series, *args, **kwargs)

    @wrapper.register(DataFrameGroupBy)
    def _(
            _data: DataFrameGroupBy,
            *args: Any,
            **kwargs: Any
    ) -> Any:
        _column = DirectRefAttr(_data, _data.obj.columns[0])
        series = evaluate_expr(_column, _data, context)
        args = evaluate_args(args, _data, context.args)
        kwargs = evaluate_kwargs(kwargs, _data, context.kwargs)
        return series.apply(func, *args, **kwargs)

    return wrapper

def register_grouped(
        func: Optional[Callable] = None,
        context: Optional[Union[Context, ContextBase]] = None,
        columns: Union[str, int] = 1
) -> Callable:
    """Register a function as a group-by-aware function"""
    if func is None:
        return lambda fun: register_grouped(
            fun,
            context=context,
            columns=columns
        )

    if isinstance(context, Context):
        context = context.value

    if columns == '*':
        return _register_grouped_coln(func, context=context)

    if columns == 1:
        return _register_grouped_col1(func, context=context)

    if columns == 0:
        return _register_grouped_col0(func, context=context)

    raise ValueError("Expect columns to be either '*', 0 or 1.")

@register_func
def starts_with(
        _data: Union[DataFrame, DataFrameGroupBy],
        match: Union[Iterable[str], str],
        ignore_case: bool = True,
        vars: Optional[Iterable[str]] = None,
) -> List[str]:
    """Select columns starting with a prefix.

    Args:
        _data: The data piped in
        match: Strings. If len>1, the union of the matches is taken.
        ignore_case: If True, the default, ignores case when matching names.
        vars: A set of variable names. If not supplied, the variables are
            taken from the data columns.

    Returns:
        A list of matched vars
    """
    return filter_columns(
        vars or objectize(_data).columns,
        match,
        ignore_case,
        lambda mat, cname: cname.startswith(mat),
    )

@register_func
def ends_with(
        _data: Union[DataFrame, DataFrameGroupBy],
        match: str,
        ignore_case: bool = True,
        vars: Optional[Iterable[str]] = None,
) -> List[str]:
    """Select columns ending with a suffix.

    Args:
        _data: The data piped in
        match: Strings. If len>1, the union of the matches is taken.
        ignore_case: If True, the default, ignores case when matching names.
        vars: A set of variable names. If not supplied, the variables are
            taken from the data columns.

    Returns:
        A list of matched vars
    """
    return filter_columns(
        vars or objectize(_data).columns,
        match,
        ignore_case,
        lambda mat, cname: cname.endswith(mat),
    )

@register_func
def contains(
        _data: Union[DataFrame, DataFrameGroupBy],
        match: str,
        ignore_case: bool = True,
        vars: Optional[Iterable[str]] = None,
) -> List[str]:
    """Select columns containing substrings.

    Args:
        _data: The data piped in
        match: Strings. If len>1, the union of the matches is taken.
        ignore_case: If True, the default, ignores case when matching names.
        vars: A set of variable names. If not supplied, the variables are
            taken from the data columns.

    Returns:
        A list of matched vars
    """
    return filter_columns(
        vars or objectize(_data).columns,
        match,
        ignore_case,
        lambda mat, cname: mat in cname,
    )

@register_func
def matches(
        _data: Union[DataFrame, DataFrameGroupBy],
        match: str,
        ignore_case: bool = True,
        vars: Optional[Iterable[str]] = None,
) -> List[str]:
    """Select columns matching regular expressions.

    Args:
        _data: The data piped in
        match: Regular expressions. If len>1, the union of the matches is taken.
        ignore_case: If True, the default, ignores case when matching names.
        vars: A set of variable names. If not supplied, the variables are
            taken from the data columns.

    Returns:
        A list of matched vars
    """
    return filter_columns(
        vars or objectize(_data).columns,
        match,
        ignore_case,
        lambda mat, cname: re.search(mat, cname),
    )

@register_func
def everything(_data: Union[DataFrame, DataFrameGroupBy]) -> List[str]:
    """Matches all columns.

    Args:
        _data: The data piped in

    Returns:
        All column names of _data
    """
    return objectize(_data).columns.to_list()

@register_func
def last_col(
        _data: Union[DataFrame, DataFrameGroupBy],
        offset: int = 0,
        vars: Optional[Iterable[str]] = None
) -> str:
    """Select last variable, possibly with an offset.

    Args:
        _data: The data piped in
        offset: The offset from the end.
            Note that this is 0-based, the same as `tidyverse`'s `last_col`
        vars: A set of variable names. If not supplied, the variables are
            taken from the data columns.

    Returns:
        The variable
    """
    vars = vars or _data.columns
    return vars[-(offset+1)]

@register_func
def all_of(
        _data: Union[DataFrame, DataFrameGroupBy],
        x: Iterable[Union[int, str]]
) -> List[str]:
    """For strict selection.

    If any of the variables in the character vector is missing,
    an error is thrown.

    Args:
        _data: The data piped in
        x: A set of variables to match the columns

    Returns:
        The matched column names

    Raises:
        ColumnNotExistingError: When any of the elements in `x` does not exist
            in `_data` columns
    """
    nonexists = set(x) - set(objectize(_data).columns)
    if nonexists:
        nonexists = ', '.join(f'`{elem}`' for elem in nonexists)
        raise ColumnNotExistingError(
            "Can't subset columns that don't exist. "
            f"Column(s) {nonexists} not exist."
        )

    return list(x)

@register_func
def any_of(_data: Union[DataFrame, DataFrameGroupBy],
           x: Iterable[Union[int, str]],
           vars: Optional[Iterable[str]] = None) -> List[str]:
    """Select but doesn't check for missing variables.

    It is especially useful with negative selections,
    when you would like to make sure a variable is removed.

    Args:
        _data: The data piped in
        x: A set of variables to match the columns

    Returns:
        The matched column names
    """
    vars = vars or objectize(_data).columns
    return [elem for elem in x if elem in vars]

@register_func((DataFrame, DataFrameGroupBy))
def where(_data: Union[DataFrame, DataFrameGroupBy], fn: Callable) -> List[str]:
    """Selects the variables for which a function returns True.

    Args:
        _data: The data piped in
        fn: A function that returns True or False.
            Currently it has to be `register_func/register_cfunction
            registered function purrr-like formula not supported yet.

    Returns:
        The matched columns
    """
    _data = objectize(_data)
    retcols = []

    pipda_type = getattr(fn, '__pipda__', None)
    for col in _data.columns:
        if not pipda_type:
            conditions = fn(_data[col])
        else:
            conditions = (
                fn(_data[col], _force_piping=True).evaluate(_data)
                if pipda_type == 'PlainFunction'
                else fn(_data, _data[col], _force_piping=True).evaluate(_data)
            )
        if isinstance(conditions, bool):
            if conditions:
                retcols.append(col)
            else:
                continue
        elif all(conditions):
            retcols.append(col)

    return retcols

@register_func((DataFrame, DataFrameGroupBy), context=Context.SELECT)
def desc(
        _data: Union[DataFrame, DataFrameGroupBy],
        col: str
) -> Union[DescSeries, SeriesGroupBy]:
    if isinstance(_data, DataFrameGroupBy):
        series = DescSeries(_data[col].obj.values, name=col)
        return series.groupby(_data.grouper, dropna=False)
    return DescSeries(_data[col].values, name=col)

@register_func(context=Context.SELECT)
def across(
        _data: DataFrame,
        _cols: Optional[Iterable[str]] = None,
        _fns: Optional[Union[Mapping[str, Callable]]] = None,
        _names: Optional[str] = None,
        *args: Any,
        **kwargs: Any
) -> Across:
    return Across(_data, _cols, _fns, _names, args, kwargs)

@register_func(context=Context.SELECT)
def c_across(
        _data: DataFrame,
        _cols: Optional[Iterable[str]] = None,
        _fns: Optional[Union[Mapping[str, Callable]]] = None,
        _names: Optional[str] = None,
        *args: Any,
        **kwargs: Any
) -> CAcross:
    return CAcross(_data, _cols, _fns, _names, args, kwargs)

@register_func(context=Context.SELECT)
def if_any(
        _data: DataFrame,
        _cols: Optional[Iterable[str]] = None,
        _fns: Optional[Union[Mapping[str, Callable]]] = None,
        _names: Optional[str] = None,
        *args: Any,
        **kwargs: Any
) -> Across:
    return IfAny(_data, _cols, _fns, _names, args, kwargs)


@register_func(context=Context.SELECT)
def if_all(
        _data: DataFrame,
        _cols: Optional[Iterable[str]] = None,
        _fns: Optional[Union[Mapping[str, Callable]]] = None,
        _names: Optional[str] = None,
        *args: Any,
        **kwargs: Any
) -> Across:
    return IfAll(_data, _cols, _fns, _names, args, kwargs)

def _ranking(
        data: Iterable[Any],
        na_last: str,
        method: str,
        percent: bool = False
) -> Iterable[float]:
    """Rank the data"""
    if not isinstance(data, Series):
        data = Series(data)

    ascending = not isinstance(data, DescSeries)

    ret = data.rank(
        method=method,
        ascending=ascending,
        pct=percent,
        na_option=(
            'keep' if na_last == 'keep'
            else 'top' if not na_last
            else 'bottom'
        )
    )
    return ret

@register_grouped(context=Context.EVAL)
def min_rank(series: Iterable[Any], na_last: str = "keep") -> Iterable[float]:
    """Rank the data using min method"""
    return _ranking(series, na_last=na_last, method='min')

@register_grouped(context=Context.EVAL)
def dense_rank(series: Iterable[Any], na_last: str = "keep") -> Iterable[float]:
    """Rank the data using dense method"""
    return _ranking(series, na_last=na_last, method='dense')

@register_grouped(context=Context.EVAL)
def percent_rank(series: Iterable[Any], na_last: str = "keep") -> Iterable[float]:
    """Rank the data using percent_rank method"""
    ranking = _ranking(series, na_last, 'min', True)
    min_rank = ranking.min()
    max_rank = ranking.max()
    ret = ranking.transform(lambda r: (r-min_rank)/(max_rank-min_rank))
    ret[ranking.isna()] = numpy.nan
    return ret

@register_grouped(context=Context.EVAL)
def cume_dist(series: Iterable[Any], na_last: str = "keep") -> Iterable[float]:
    """Rank the data using percent_rank method"""
    ranking = _ranking(series, na_last, 'min')
    max_ranking = ranking.max()
    ret = ranking.transform(lambda r: ranking.le(r).sum() / max_ranking)
    ret[ranking.isna()] = numpy.nan
    return ret

@register_grouped(context=Context.EVAL)
def ntile(series: Iterable[Any], n: int) -> Iterable[Any]:
    return pandas.cut(series, n, labels=range(n))

@register_grouped(context=Context.EVAL)
def sum(series: Iterable[Any], na_rm: bool = False) -> float:
    return numpy.nansum(series) if na_rm else numpy.sum(series)

@register_grouped(context=Context.EVAL)
def mean(series: Iterable[Any], na_rm: bool = False) -> float:
    return numpy.nanmean(series) if na_rm else numpy.mean(series)

@register_grouped(context=Context.EVAL)
def min(series: Iterable[Any], na_rm: bool = False) -> float:
    return numpy.nanmin(series) if na_rm else numpy.min(series)

@register_grouped(context=Context.EVAL)
def max(series: Iterable[Any], na_rm: bool = False) -> float:
    return numpy.nanmax(series) if na_rm else numpy.max(series)

@register_grouped(context=Context.EVAL)
def sd(
        series: Iterable[Any],
        na_rm: bool = False,
        # numpy default is 0. Make it 1 to be consistent with R
        ddof: int = 1
) -> float:
    return (
        numpy.nanstd(series, ddof=ddof) if na_rm
        else numpy.std(series, ddof=ddof)
    )


@register_func((DataFrame, DataFrameGroupBy), context=Context.EVAL)
def pmin(
        _data: Union[DataFrame, DataFrameGroupBy],
        *series: Union[Series, SeriesGroupBy],
        na_rm: bool = False
) -> Iterable[float]:
    series = (objectize(ser) for ser in series)
    return [min(_data, elem, na_rm=na_rm) for elem in zip(*series)]

@register_func((DataFrame, DataFrameGroupBy), context=Context.EVAL)
def pmax(
        _data: Union[DataFrame, DataFrameGroupBy],
        *series: Union[Series, SeriesGroupBy],
        na_rm: bool = False
) -> Iterable[float]:
    series = (objectize(ser) for ser in series)
    return [max(_data, elem, na_rm=na_rm) for elem in zip(*series)]

@register_func((DataFrame, DataFrameGroupBy), context=Context.EVAL)
def case_when(
        _data: Union[DataFrame, DataFrameGroupBy],
        *when_cases: Any
) -> Series:
    if len(when_cases) % 2 != 0:
        raise ValueError('Number of arguments of case_when should be even.')

    nrow = objectize(_data).shape[0]
    df = DataFrame({'x': [numpy.nan] * nrow})
    when_cases = reversed(list(zip(when_cases[0::2], when_cases[1::2])))
    for case, ret in when_cases:
        if case is True:
            df['x'] = ret
        else:
            df.loc[case, 'x'] = ret

    return df.x

@register_grouped(context=Context.EVAL, columns=0)
def n(series: Iterable[Any]) -> int:
    return len(series)

@register_grouped(context=Context.EVAL, columns=0)
def row_number(series: Iterable[Any]) -> Iterable[int]:
    if isinstance(series, Series):
        return Series(range(len(series)))
    return series.cumcount()



# Functions without data arguments
# --------------------------------


@register_func(None, context=Context.UNSET)
def c(*elems: Any) -> Collection:
    """Mimic R's concatenation. Named one is not supported yet
    All elements passed in will be flattened.

    Args:
        _data: The data piped in
        *elems: The elements

    Returns:
        A collection of elements
    """
    return Collection(*elems)

@register_func(None, context=Context.EVAL)
def round(
        number: Union[Series, SeriesGroupBy, float],
        ndigits: int = 0
) -> float:
    number = objectize(number)
    if isinstance(number, Series):
        return number.round(ndigits)
    return builtins.round(number, ndigits)

@register_func(None, context=Context.EVAL)
def sqrt(x: Any) -> bool:
    x = objectize(x)
    if isinstance(x, Series):
        return x.apply(sqrt)
    return math.sqrt(x) if x > 0 else math.sqrt(-x) * 1j

@register_func(None, context=Context.EVAL)
def coalesce(x: Any, replace: Any) -> Any:
    x = objectize(x)
    if isinstance(x, Iterable):
        if not isinstance(replace, Iterable):
            replace = [replace] * len(x)
        elif len(replace) != len(x):
            raise ValueError(
                f"Expect length {len(x)} for coalesce replacement, "
                f"got {len(replace)}"
            )
        return [
            rep if numpy.math.isnan(elem) else elem
            for elem, rep in zip(x, replace)
        ]

    return replace if numpy.math.isnan(x) else x

@register_func(None, context=Context.EVAL)
def is_numeric(x: Any) -> bool:
    x = objectize(x)
    if isinstance(x, Series):
        return is_numeric_dtype(x)
    return isinstance(x, (int, float))

def is_character(x: Any) -> bool:
    """Mimic the is.character function in R

    Args:
        x: The elements to check

    Returns:
        True if
    """
    x = objectize(x)
    if isinstance(x, Series):
        return is_string_dtype(x)
    return isinstance(x, str)

@register_func(None, context=Context.EVAL)
def is_categorical(x: Union[Series, SeriesGroupBy]) -> bool:
    x = objectize(x)
    return is_categorical_dtype(x)

@register_func(None, context=Context.EVAL)
def is_double(x: Any) -> bool:
    x = objectize(x)
    if isinstance(x, Series):
        return is_float_dtype(x)
    return isinstance(x, float)

is_float = is_double

@register_func(None, context=Context.EVAL)
def is_na(x: Any) -> bool:
    x = objectize(x)
    if isinstance(x, Series):
        return x.isna()
    return numpy.isnan(x)


@register_func(None)
def seq_along(along_with):
    return list(range(len(along_with)))

@register_func(None)
def seq_len(length_out):
    return list(range(length_out))

@register_func(None, context=Context.EVAL)
def seq(from_=None, to=None, by=None, length_out=None, along_with=None):
    if along_with is not None:
        return seq_along(along_with)
    if from_ is not None and not isinstance(from_, (int, float)):
        return seq_along(from_)
    if length_out is not None and from_ is None and to is None:
        return seq_len(length_out)

    if from_ is None:
        from_ = 0
    elif to is None:
        from_, to = 0, from_

    if length_out is not None:
        by = (float(to) - float(from_)) / float(length_out)
    elif by is None:
        by = 1
        length_out = to - from_
    else:
        length_out = (to - from_ + by - by/10.0) // by
    return [from_ + n * by for n in range(int(length_out))]

@register_func(None, context=Context.EVAL)
def as_categorical(x: Union[Series, SeriesGroupBy]) -> Series:
    x = objectize(x)
    return x.astype('category')

@register_func(None, context=Context.EVAL)
def as_character(x: Union[Series, SeriesGroupBy]) -> Series:
    x = objectize(x)
    return x.astype('str')

@register_func(None)
def num_range(
        prefix: str,
        range: Iterable[int],
        width: Optional[int] = None
) -> List[str]:
    """Matches a numerical range like x01, x02, x03.

    Args:
        _data: The data piped in
        prefix: A prefix that starts the numeric range.
        range: A sequence of integers, like `range(3)` (produces `0,1,2`).
        width: Optionally, the "width" of the numeric range.
            For example, a range of 2 gives "01", a range of three "001", etc.

    Returns:
        A list of ranges with prefix.
    """
    return [
        f"{prefix}{elem if not width else str(elem).zfill(width)}"
        for elem in range
    ]


@register_func(None, context=Context.EVAL)
def abs(x: Any) -> bool:
    x = objectize(x)
    if isinstance(x, Series):
        return x.abs()
    builtins.abs(x)

# todo: figure out singledispatch for as_date
def _as_date_format(
        x: str,
        format: Optional[str],
        try_formats: Optional[Iterator[str]],
        optional: bool,
        offset: datetime.timedelta
) -> datetime.date:
    try_formats = try_formats or [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S"
    ]
    if not format:
        format = try_formats
    else:
        format = [format]

    for fmt in format:
        try:
            return (datetime.datetime.strptime(x, fmt) + offset).date()
        except ValueError:
            continue
    else:
        if optional:
            return numpy.nan
        else:
            raise ValueError(
                "character string is not in a standard unambiguous format"
            )

def _as_date_diff(
        x: int,
        origin: Union[DateType, datetime.datetime],
        offset: datetime.timedelta
) -> datetime.date:
    if isinstance(origin, str):
        origin = _as_date(origin)

    dt = origin + datetime.timedelta(days=x) + offset
    if isinstance(dt, datetime.date):
        return dt

    return dt.date()

def _as_date(
        x: DateType,
        format: Optional[str] = None,
        try_formats: Optional[List[str]] = None,
        optional: bool = False,
        tz: Union[int, datetime.timedelta] = 0,
        origin: Optional[Union[DateType, datetime.datetime]] = None
) -> datetime.date:
    """Convert an object to a datetime.date object

    See: https://rdrr.io/r/base/as.Date.html

    Args:
        x: Object that can be converted into a datetime.date object
        format:  If not specified, it will try try_formats one by one on
            the first non-NaN element, and give an error if none works.
            Otherwise, the processing is via strptime
        try_formats: vector of format strings to try if format is not specified.
        optional: indicating to return NA (instead of signalling an error)
            if the format guessing does not succeed.
        origin: a datetime.date/datetime object, or something which can be
            coerced by as_date(origin, ...) to such an object.
        tz: a time zone offset or a datetime.timedelta object.
            Note that time zone name is not supported yet.

    Returns:
        The datetime.date object

    Raises:
        ValueError: When string is not in a standard unambiguous format
    """
    if isinstance(tz, (int, numpy.integer)):
        tz = datetime.timedelta(hours=int(tz))

    if isinstance(x, datetime.date):
        return x + tz

    if isinstance(x, datetime.datetime):
        return (x + tz).date()

    if isinstance(x, str):
        return _as_date_format(
            x,
            format=format,
            try_formats=try_formats,
            optional=optional,
            offset=tz
        )

    if isinstance(x, (int, numpy.integer)):
        return _as_date_diff(int(x), origin=origin, offset=tz)

    raise ValueError("character string is not in a standard unambiguous format")

@register_func(None, context=Context.EVAL)
def _as_date(
        x: Union[Series, SeriesGroupBy],
        **kwargs: Any
) -> datetime.date:
    x = objectize(x)
    return x.transform(_as_date, **kwargs)
