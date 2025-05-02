from typing import List, Union, Dict
import pandas as pd
import duckdb

def extract(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path)

def transform(
    df: pd.DataFrame,
    partners: Union[str, List[str]]
) -> pd.DataFrame:
    if isinstance(partners, str):
        partners = [partners]
    df['final_network_partner'] = (
        df['final_network_partner']
          .astype(str)
          .str.strip()
    )
    filtered = df[df['final_network_partner'].isin(partners)].copy()
    filtered['date'] = pd.to_datetime(filtered['date'])
    return filtered[['date', 'item', 'weight', 'final_network_partner']]

def split_by_partner(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Split the DataFrame into a dict of DataFrames, one per partner.
    Each DataFrame has columns: date, item, weight, final_network_partner
    """
    df = df.copy()
    df['final_network_partner'] = (
        df['final_network_partner']
          .astype(str)
          .str.strip()
    )
    df['date'] = pd.to_datetime(df['date'])

    dfs: Dict[str, pd.DataFrame] = {}
    for partner, group in df.groupby('final_network_partner'):
        tmp = group.copy()
        dfs[partner] = tmp[['date', 'item', 'weight', 'final_network_partner']]
    return dfs

def persist_parcels_table(
    df: pd.DataFrame,
    duckdb_path: str,
    table_name: str = 'parcels'
) -> None:
    con = duckdb.connect(database=duckdb_path)
    con.register('df', df)
    con.execute(f"""
        DROP TABLE IF EXISTS {table_name};
        CREATE TABLE {table_name} AS SELECT * FROM df;
    """)
    con.close()

def persist_per_partner(
    df: pd.DataFrame,
    duckdb_path: str,
    schema: str = 'main'
) -> None:
    """
    Given a DataFrame, split it by partner and write each
    to its own DuckDB table named after the partner.
    """
    con = duckdb.connect(database=duckdb_path)
    existing = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = ?",
        [schema]
    ).df()['table_name'].tolist()
    for t in existing:
        if t.startswith('partner_'):
            con.execute(f"DROP TABLE IF EXISTS {t}")
    for partner, subdf in split_by_partner(df).items():
        tbl = 'partner_' + partner.lower().replace(' ', '_')
        con.register('tmp', subdf)
        con.execute(f"CREATE TABLE {tbl} AS SELECT * FROM tmp")
    con.close()
