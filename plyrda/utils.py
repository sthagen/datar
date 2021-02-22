from typing import Any, Callable, Iterable, List, Union

from pandas import DataFrame
from pandas.core.series import Series
from pandas.core.groupby import DataFrameGroupBy, SeriesGroupBy
from pipda.context import Context

from .exceptions import ColumnNameInvalidError, ColumnNotExistingError

def list_diff(list1: Iterable[Any], list2: Iterable[Any]) -> List[Any]:
    """Get the difference between two lists and keep the order

    Args:
        list1: The first list
        list2: The second list

    Returns:
        The list1 elements that don't exist in list2.
    """
    return [elem for elem in list1 if elem not in list2]

def list_intersect(list1: Iterable[Any], list2: Iterable[Any]) -> List[Any]:
    """Get the intersect between two lists and keep the order

    Args:
        list1: The first list
        list2: The second list

    Returns:
        The list1 elements that also exist in list2.
    """
    return [elem for elem in list1 if elem in list2]

def list_union(list1: Iterable[Any], list2: Iterable[Any]) -> List[Any]:
    """Get the union between two lists and keep the order

    Args:
        list1: The first list
        list2: The second list

    Returns:
        The elements with elements in either list1 or list2
    """
    return list1 + list_diff(list2, list1)

def check_column(column: Any) -> None:
    """Check if a column is valid

    Args:
        column: The column

    Raises:
        ColumnNameInvalidError: When the column name is invalid
    """
    from .middlewares import Inverted, Across
    if not isinstance(column, (
            (int, str, list, set, tuple, Inverted, Across, slice)
    )):
        raise ColumnNameInvalidError(
            'Invalid column, expected int, str, list, tuple, c(), across(), '
            f'f.column, -c() or -f.column, got {type(column)}'
        )

def expand_collections(collections: Any) -> List[Any]:
    """Expand and flatten all iterables in the collections

    Args:
        collections: The collections of elements or iterables

    Returns:
        The flattened list
    """
    if not isinstance(collections, (list, tuple, set)):
        return [collections]
    ret = []
    for collection in collections:
        ret.extend(expand_collections(collection))
    return ret

def filter_columns(
        all_columns: Iterable[str],
        match: Union[Iterable[str], str],
        ignore_case: bool,
        func: Callable[[str, str], bool]
) -> List[str]:
    """Filter the columns with given critera

    Args:
        all_columns: The column pool to filter
        match: Strings. If len>1, the union of the matches is taken.
        ignore_case: If True, the default, ignores case when matching names.
        func: A function to define how to filter.

    Returns:
        A list of matched vars
    """
    if not isinstance(match, (tuple, list, set)):
        match = [match]

    ret = []
    for mat in match:
        for column in all_columns:
            if column in ret:
                continue
            if (func(
                    mat.lower() if ignore_case else mat,
                    column.lower() if ignore_case else column
            )):
                ret.append(column)
    return ret

def sanitize_slice(slc: slice, all_columns: List[str]) -> slice:
    int_start, int_stop, step = slc.start, slc.stop, slc.step
    if isinstance(int_start, str):
        int_start = all_columns.index(int_start)
    if isinstance(int_stop, str):
        int_stop = all_columns.index(int_stop)

    int_stop += 1
    if step == 0:
        step = None
        int_stop -= 1
    return slice(int_start, int_stop, step)

def select_columns(
        all_columns: Iterable[str],
        *columns: Any,
        raise_nonexist: bool = True
) -> List[str]:
    """Select columns

    Args:
        all_columns: The column pool to select
        *columns: arguments to select from the pool
        raise_nonexist: Whether raise exception when column not exists
            in the pool

    Returns:
        The selected columns

    Raises:
        ColumnNameInvalidError: When the column is invalid to select
        ColumnNotExistingError: When the column does not exist in the pool
    """
    from .middlewares import Inverted, Across
    if not isinstance(all_columns, list):
        all_columns = list(all_columns)

    negs = [isinstance(column, Inverted) for column in columns]
    has_negs = any(negs)
    if has_negs and not all(negs):
        raise ColumnNameInvalidError(
            'Either none or all of the columns are negative.'
        )

    selected = []
    for column in columns:
        check_column(column)
        if isinstance(column, int): # 1, -1
            # -1 will do select instead of removal
            selected.append(all_columns[column])
        elif isinstance(column, (list, tuple, set)): # ['x', 'y']
            selected.extend(column)
        elif isinstance(column, Inverted):
            selected.extend(column.elems)
        elif isinstance(column, slice):
            selected.extend(all_columns[sanitize_slice(column, all_columns)])
        elif isinstance(column, Across):
            selected.extend(column.evaluate(Context.SELECT))
        else:
            selected.append(column)

    if raise_nonexist:
        for sel in selected:
            if sel not in all_columns:
                raise ColumnNotExistingError(
                    f"Column `{sel}` doesn't exist."
                )

    if has_negs:
        selected = list_diff(all_columns, selected)
    return selected

def series_expandable(
        df_or_series: Union[DataFrame, Series],
        series_or_df: Union[DataFrame, Series]
) -> bool:
    if (not isinstance(df_or_series, (Series, DataFrame)) or
            not isinstance(series_or_df, (Series, DataFrame))):
        return False

    if type(df_or_series) is type(series_or_df):
        if df_or_series.shape[0] < series_or_df.shape[0]:
            series, df = df_or_series, series_or_df
        else:
            df, series = df_or_series, series_or_df
    elif isinstance(df_or_series, Series):
        series, df = df_or_series, series_or_df
    else:
        df, series = df_or_series, series_or_df

    return series.index.name in df.columns

def series_expand(series: Union[DataFrame, Series], df: DataFrame):
    if isinstance(series, DataFrame):
        #assert series.shape[1] == 1
        series = series.iloc[:, 0]
    return df[series.index.name].map(series)

def align_value(
        value: Any,
        data: Union[DataFrame, DataFrameGroupBy]
) -> Iterable[Any]:
    """Normalize possible series data to add to the data or compare with
    other series of the data"""
    if isinstance(data, DataFrameGroupBy):
        data = data.obj
    if isinstance(value, (DataFrameGroupBy, SeriesGroupBy)):
        value = value.obj

    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        value = [value]

    if series_expandable(value, data):
        return series_expand(value, data)

    len_series = (
        value.shape[0] if isinstance(value, (DataFrame, Series))
        else len(value)
    )

    if len_series == data.shape[0]:
        return value
    if data.shape[0] % len_series == 0:
        nrepeat = data.shape[0] // len_series
        if isinstance(value, (list, tuple)):
            return value * nrepeat
        return value.append([value] * (nrepeat - 1))
    return value
